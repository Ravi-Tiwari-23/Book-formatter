from __future__ import annotations

import hashlib
import re
import unicodedata
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Collection

import pymupdf
from rapidfuzz import fuzz, process


class IntegrityDifferenceType(str, Enum):
    MISSING = "MISSING"
    DUPLICATED = "DUPLICATED"
    UNEXPECTED = "UNEXPECTED"
    MODIFIED = "MODIFIED"
    ORDER_CHANGED = "ORDER_CHANGED"


_QUOTE_TRANSLATION = str.maketrans(
    {
        "\u2018": "'",
        "\u2019": "'",
        "\u201a": "'",
        "\u201b": "'",
        "\u201c": '"',
        "\u201d": '"',
        "\u201e": '"',
        "\u201f": '"',
        "\u00ab": '"',
        "\u00bb": '"',
        "\u2010": "-",
        "\u2011": "-",
        "\u2012": "-",
        "\u2013": "-",
        "\u2014": "-",
        "\u2212": "-",
    }
)


def normalize_integrity_text(value: str, *, for_matching: bool = False) -> str:
    """Normalize presentation differences without rewriting approved words."""
    value = unicodedata.normalize("NFC", value)
    value = value.translate(_QUOTE_TRANSLATION)
    value = value.replace("\u00a0", " ").replace("\u00ad", "")
    value = re.sub(r"[\u200b\u200c\u200d\u2060\ufeff]", "", value)
    value = re.sub(r"(?<=\w)-\s+(?=\w)", "-", value, flags=re.UNICODE)
    value = re.sub(r"\s+", " ", value).strip()
    if for_matching:
        # PDF text extractors commonly insert/remove spaces beside punctuation
        # and change typographic punctuation/case. These are presentation
        # differences, not permission to rewrite any word or digit.
        value = re.sub(r"\s*([/,:;!?।])\s*", r"\1", value)
        value = re.sub(r"\s+\.", ".", value)
        value = re.sub(r"([([{])\s+", r"\1", value)
        value = re.sub(r"\s+([)\]}])", r"\1", value)
        value = re.sub(r"\s*-\s*", "-", value)
        value = value.casefold()
    return value


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest() if value else ""


@dataclass(slots=True)
class TextUnit:
    id: str
    chapter_id: str
    chapter_title: str
    order: int
    text: str
    kind: str = "paragraph"
    source_page: int | None = None
    original_text: str = ""

    @property
    def normalized_text(self) -> str:
        return normalize_integrity_text(self.text)

    @property
    def text_sha256(self) -> str:
        return _sha256(self.normalized_text)

    @property
    def match_text(self) -> str:
        return normalize_integrity_text(self.text, for_matching=True)


@dataclass(slots=True)
class IntegrityIssue:
    canonical_id: str
    chapter_id: str
    chapter_title: str
    unit_order: int
    difference_type: IntegrityDifferenceType
    expected_text: str = ""
    actual_text: str = ""
    expected_sha256: str = ""
    actual_sha256: str = ""
    expected_length: int = 0
    actual_length: int = 0
    difference_excerpt: str = ""
    status: str = "NEEDS_REVIEW"
    severity: str = "ERROR"
    source_page: int | None = None
    output_page: int | None = None
    original_text: str = ""
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["difference_type"] = self.difference_type.value
        return result


@dataclass(slots=True)
class IntegrityReport:
    stage: str
    passed: bool
    checked_units: int
    chapters_checked: int
    issues: list[IntegrityIssue] = field(default_factory=list)
    resynchronized: bool = False

    @property
    def summary(self) -> dict[str, int]:
        counts = Counter(issue.difference_type.value for issue in self.issues)
        return {kind.value: counts.get(kind.value, 0) for kind in IntegrityDifferenceType}

    @property
    def fatal_issues(self) -> list[IntegrityIssue]:
        return [issue for issue in self.issues if issue.severity == "ERROR"]

    @property
    def warnings(self) -> list[IntegrityIssue]:
        return [issue for issue in self.issues if issue.severity == "WARNING"]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": "PASSED" if self.passed else "FAILED",
            "passed": self.passed,
            "stage": self.stage,
            "checked_units": self.checked_units,
            "chapters_checked": self.chapters_checked,
            "resynchronized": self.resynchronized,
            "summary": self.summary,
            "issues": [issue.to_dict() for issue in self.issues],
            "fatal_issue_count": len(self.fatal_issues),
            "warning_count": len(self.warnings),
        }


class ProductionIntegrityError(RuntimeError):
    def __init__(
        self,
        report: IntegrityReport,
        report_path: str | Path | None = None,
    ) -> None:
        self.report = report
        self.report_path = Path(report_path) if report_path else None
        count = len(report.issues)
        super().__init__(
            f"Final build blocked: text integrity verification found {count} "
            f"issue{'s' if count != 1 else ''}."
        )


def _issue(
    difference_type: IntegrityDifferenceType,
    *,
    expected: TextUnit | None = None,
    actual: TextUnit | None = None,
    output_page: int | None = None,
) -> IntegrityIssue:
    unit = expected or actual
    assert unit is not None
    expected_text = expected.text if expected else ""
    actual_text = actual.text if actual else ""
    expected_normalized = normalize_integrity_text(expected_text)
    actual_normalized = normalize_integrity_text(actual_text)
    if expected_text and actual_text:
        excerpt = f"Expected: {expected_text[:180]} | Renderer: {actual_text[:180]}"
    elif expected_text:
        excerpt = f"Possible missing text: {expected_text[:220]}"
    else:
        excerpt = f"Possible unexpected text: {actual_text[:220]}"
    reasons = {
        IntegrityDifferenceType.MISSING: "Approved content was not found in the generated PDF",
        IntegrityDifferenceType.DUPLICATED: "Approved content appears more than once in the generated PDF",
        IntegrityDifferenceType.UNEXPECTED: "Unmatched text was found in the generated PDF body",
        IntegrityDifferenceType.MODIFIED: "Generated PDF text differs from the approved text",
        IntegrityDifferenceType.ORDER_CHANGED: "Generated PDF content is not in the approved order",
    }
    return IntegrityIssue(
        canonical_id=unit.id,
        chapter_id=unit.chapter_id,
        chapter_title=unit.chapter_title,
        unit_order=unit.order,
        difference_type=difference_type,
        expected_text=expected_text,
        actual_text=actual_text,
        expected_sha256=_sha256(expected_normalized),
        actual_sha256=_sha256(actual_normalized),
        expected_length=len(expected_normalized),
        actual_length=len(actual_normalized),
        difference_excerpt=excerpt,
        source_page=expected.source_page if expected else None,
        output_page=output_page,
        original_text=expected.original_text if expected else "",
        reason=reasons[difference_type],
    )


def compare_text_units(
    expected: list[TextUnit],
    actual: list[TextUnit],
    *,
    stage: str,
) -> IntegrityReport:
    expected = [unit for unit in expected if unit.normalized_text]
    actual = [unit for unit in actual if unit.normalized_text]
    expected_by_id = {unit.id: unit for unit in expected}
    actual_by_id: dict[str, list[TextUnit]] = defaultdict(list)
    for unit in actual:
        actual_by_id[unit.id].append(unit)

    issues: list[IntegrityIssue] = []
    for unit in expected:
        matches = actual_by_id.get(unit.id, [])
        if not matches:
            issues.append(_issue(IntegrityDifferenceType.MISSING, expected=unit))
            continue
        if len(matches) > 1:
            issues.append(
                _issue(
                    IntegrityDifferenceType.DUPLICATED,
                    expected=unit,
                    actual=matches[0],
                )
            )
        if unit.match_text != matches[0].match_text:
            issues.append(
                _issue(
                    IntegrityDifferenceType.MODIFIED,
                    expected=unit,
                    actual=matches[0],
                )
            )

    for unit in actual:
        if unit.id not in expected_by_id:
            issues.append(_issue(IntegrityDifferenceType.UNEXPECTED, actual=unit))

    expected_order = [unit.id for unit in expected if unit.id in actual_by_id]
    actual_order: list[str] = []
    seen: set[str] = set()
    for unit in actual:
        if unit.id in expected_by_id and unit.id not in seen:
            actual_order.append(unit.id)
            seen.add(unit.id)
    if actual_order != expected_order and expected_order:
        first_id = next(
            (
                identity
                for index, identity in enumerate(expected_order)
                if index >= len(actual_order) or actual_order[index] != identity
            ),
            expected_order[0],
        )
        expected_unit = expected_by_id[first_id]
        actual_unit = next(
            (unit for unit in actual if unit.id == first_id), expected_unit
        )
        issues.append(
            _issue(
                IntegrityDifferenceType.ORDER_CHANGED,
                expected=expected_unit,
                actual=actual_unit,
            )
        )

    chapters = {unit.chapter_id for unit in expected}
    return IntegrityReport(
        stage=stage,
        passed=not issues,
        checked_units=len(expected),
        chapters_checked=len(chapters),
        issues=issues,
    )


def _actual_text_records(pdf_path, page_index, height):
    """Read PDF marked-content text, honoring ActualText (ISO 32000).

    MuPDF currently appends residual glyph text after some Indic ActualText
    runs. Read these runs from the PDF itself, never from the approved input.
    Geometry and font size still identify headings and page furniture.
    """
    from pypdf import PdfReader
    page = PdfReader(pdf_path).pages[page_index]
    records, stack = [], []

    def operand(op, args, cm, tm):
        if op in (b'BDC', b'BMC'):
            props = args[1] if op == b'BDC' and len(args) > 1 else {}
            actual = props.get('/ActualText') if hasattr(props, 'get') else None
            stack.append({'text': actual, 'emitted': False})
        elif op == b'EMC' and stack:
            stack.pop()

    def visit(text, cm, tm, font, size):
        if not text.strip():
            return
        actual = next((s for s in stack if s['text'] is not None), None)
        if actual:
            if actual['emitted']:
                return
            text = str(actual['text'])
            actual['emitted'] = True
        x = tm[4] * cm[0] + tm[5] * cm[2] + cm[4]
        y = height - (tm[4] * cm[1] + tm[5] * cm[3] + cm[5])
        effective_size = size * (cm[2] ** 2 + cm[3] ** 2) ** .5
        records.append((x, y - effective_size, x, y, text, effective_size))

    page.extract_text(visitor_operand_before=operand, visitor_text=visit)
    return records


def _extract_pdf_body_pages(
    pdf_path: str | Path,
    *,
    excluded_leading_pages: int = 0,
    excluded_texts: Collection[str] = (),
) -> list[tuple[int, str]]:
    """Extract semantic body text while excluding position-identified furniture."""
    excluded_normalized = {
        normalize_integrity_text(value).casefold()
        for value in excluded_texts
        if normalize_integrity_text(value)
    }
    pages: list[
        tuple[int, float, list[tuple[float, float, float, float, str, float]]]
    ] = []
    repeated_edges: dict[str, set[int]] = defaultdict(set)
    with pymupdf.open(pdf_path) as document:
        for page_index, page in enumerate(document):
            if page_index < excluded_leading_pages:
                continue
            blocks: list[tuple[float, float, float, float, str, float]] = []
            if b'/ActualText' in page.read_contents():
                blocks = _actual_text_records(pdf_path, page_index, page.rect.height)
                pages.append((page_index + 1, page.rect.height, blocks))
                continue
            page_dict = page.get_text("dict", sort=True)
            for block in page_dict.get("blocks", []):
                for line in block.get("lines", []):
                    text = "".join(span.get("text", "") for span in line.get("spans", []))
                    normalized = normalize_integrity_text(text)
                    if not normalized:
                        continue
                    x0, y0, x1, y1 = line["bbox"]
                    max_size = max(
                        (float(span.get("size", 0.0)) for span in line.get("spans", [])),
                        default=0.0,
                    )
                    record = (
                        float(x0),
                        float(y0),
                        float(x1),
                        float(y1),
                        text,
                        max_size,
                    )
                    blocks.append(record)
                    if y1 <= 45 or y0 >= page.rect.height - 45:
                        if not re.fullmatch(r"(?:page\s*)?\d+", normalized, re.I):
                            repeated_edges[normalized].add(page_index)
            pages.append((page_index + 1, page.rect.height, blocks))

    repeated = {text for text, page_ids in repeated_edges.items() if len(page_ids) >= 2}
    page_parts: list[tuple[int, str]] = []
    for page_number, height, blocks in pages:
        parts: list[str] = []
        for _x0, y0, _x1, y1, text, max_size in blocks:
            normalized = normalize_integrity_text(text)
            if normalized.casefold() in excluded_normalized:
                continue
            # Renderer headings begin at 12.5pt; body copy is 10.25pt. Keep
            # generated navigation/heading text outside the approved body QA.
            if max_size >= 12.0:
                continue
            if (max_size <= 10.0 and re.fullmatch(r"\d(?:\s+\d)+", normalized)) or (abs(max_size - 9) < .05 and normalized.isdigit()):
                continue
            if re.fullmatch(r"Source image\s*-\s*page\s+\d+", normalized, re.I):
                continue
            at_top_or_bottom = y1 <= 45 or y0 >= height - 45
            if at_top_or_bottom:
                if normalized in repeated:
                    continue
                if y0 >= height - 55 and re.fullmatch(
                    r"(?:page\s*)?\d+", normalized, re.I
                ):
                    continue
                parts.append(text)
            else:
                parts.append(text)
        normalized_page = normalize_integrity_text(" ".join(parts))
        if normalized_page:
            page_parts.append((page_number, normalized_page))
    return page_parts


def extract_pdf_body_text(
    pdf_path: str | Path,
    *,
    excluded_leading_pages: int = 0,
    excluded_texts: Collection[str] = (),
) -> str:
    """Extract semantic body text while excluding verified layout furniture."""
    return normalize_integrity_text(
        " ".join(
            text
            for _page, text in _extract_pdf_body_pages(
                pdf_path,
                excluded_leading_pages=excluded_leading_pages,
                excluded_texts=excluded_texts,
            )
        )
    )


def verify_rendered_pdf(
    pdf_path: str | Path,
    expected_units: list[TextUnit],
    *,
    excluded_leading_pages: int = 0,
    excluded_texts: Collection[str] = (),
) -> IntegrityReport:
    expected = [unit for unit in expected_units if unit.normalized_text]
    body_pages = _extract_pdf_body_pages(
        pdf_path,
        excluded_leading_pages=excluded_leading_pages,
        excluded_texts=excluded_texts,
    )
    output_parts: list[str] = []
    page_ranges: list[tuple[int, int, int]] = []
    cursor = 0
    for page_number, page_text in body_pages:
        page_match_text = normalize_integrity_text(page_text, for_matching=True)
        if not page_match_text:
            continue
        if output_parts:
            separator = ""
            if not re.search(r"[/,:;!?।-]$", output_parts[-1]) and not re.match(
                r"^[/,:;!?।)\]}-]", page_match_text
            ):
                separator = " "
            output_parts.append(separator)
            cursor += len(separator)
        start = cursor
        output_parts.append(page_match_text)
        cursor += len(page_match_text)
        page_ranges.append((start, cursor, page_number))
    output = "".join(output_parts)

    def page_for_position(position: int) -> int | None:
        return next(
            (page for start, end, page in page_ranges if start <= position < end),
            None,
        )

    segments = [
        segment
        for segment in re.split(r"(?<=[.!?।])\s+", output)
        if normalize_integrity_text(segment, for_matching=True)
    ]
    issues: list[IntegrityIssue] = []
    positions: list[tuple[int, TextUnit]] = []
    modified_segments: list[str] = []
    assigned_spans: list[tuple[int, int]] = []
    exact_occurrences: dict[str, list[tuple[int, int]]] = {}

    def occurrences(value: str) -> list[tuple[int, int]]:
        result = []
        start = 0
        while (position := output.find(value, start)) >= 0:
            result.append((position, position + len(value)))
            start = position + 1
        return result

    def overlaps_assigned(span: tuple[int, int]) -> bool:
        return any(span[0] < end and start < span[1] for start, end in assigned_spans)

    exact_values = {
        unit.match_text
        for unit in expected
        if output.count(unit.match_text)
    }
    modification_candidates = [
        segment
        for segment in segments
        if normalize_integrity_text(segment, for_matching=True) not in exact_values
    ]

    # Allocate exact matches longest-first so a short approved label cannot
    # claim text that belongs to a later, longer approved paragraph.
    exact_assignments: dict[str, tuple[int, int]] = {}
    for unit in sorted(expected, key=lambda item: len(item.match_text), reverse=True):
        spans = exact_occurrences.setdefault(unit.match_text, occurrences(unit.match_text))
        available = next((span for span in spans if not overlaps_assigned(span)), None)
        if available:
            assigned_spans.append(available)
            exact_assignments[unit.id] = available

    for unit in expected:
        normalized = unit.match_text
        available = exact_assignments.get(unit.id)
        if available:
            positions.append((available[0], unit))
            continue

        best = (
            process.extractOne(normalized, modification_candidates, scorer=fuzz.ratio)
            if modification_candidates
            else None
        )
        if best and best[1] >= 65:
            actual_text = str(best[0])
            actual = TextUnit(
                id=unit.id,
                chapter_id=unit.chapter_id,
                chapter_title=unit.chapter_title,
                order=unit.order,
                text=actual_text,
                kind=unit.kind,
                source_page=unit.source_page,
                original_text=unit.original_text,
            )
            issues.append(
                _issue(
                    IntegrityDifferenceType.MODIFIED,
                    expected=unit,
                    actual=actual,
                    output_page=page_for_position(output.find(actual_text)),
                )
            )
            positions.append((output.find(actual_text), unit))
            modified_segments.append(actual_text)
            modification_candidates.remove(actual_text)
        else:
            issues.append(_issue(IntegrityDifferenceType.MISSING, expected=unit))

    # Count only occurrences that remain outside every expected unit's assigned
    # span. A short approved unit appearing inside a longer approved unit is not
    # a second rendered copy of that short unit.
    for unit in expected:
        if any(not overlaps_assigned(span) for span in exact_occurrences[unit.match_text]):
            issues.append(
                _issue(
                    IntegrityDifferenceType.DUPLICATED,
                    expected=unit,
                    actual=unit,
                    output_page=page_for_position(
                        next(
                            span[0]
                            for span in exact_occurrences[unit.match_text]
                            if not overlaps_assigned(span)
                        )
                    ),
                )
            )

    ordered_positions = [position for position, _unit_value in positions]
    if len(ordered_positions) > 1 and ordered_positions != sorted(ordered_positions):
        first_out_of_order = next(
            unit
            for index, (_position, unit) in enumerate(positions)
            if index and positions[index - 1][0] > positions[index][0]
        )
        issues.append(
            _issue(
                IntegrityDifferenceType.ORDER_CHANGED,
                expected=first_out_of_order,
                actual=first_out_of_order,
                output_page=page_for_position(
                    next(position for position, unit in positions if unit is first_out_of_order)
                ),
            )
        )

    residual = output
    for unit in expected:
        residual = residual.replace(unit.match_text, " ", 1)
    for segment in modified_segments:
        residual = residual.replace(segment, " ", 1)
    residual = normalize_integrity_text(residual, for_matching=True)
    if residual:
        residual_position = output.find(residual)
        issues.append(
            _issue(
                IntegrityDifferenceType.UNEXPECTED,
                actual=TextUnit(
                    id="post-render-unexpected",
                    chapter_id="",
                    chapter_title="Unmatched output text",
                    order=len(expected),
                    text=residual,
                ),
                output_page=page_for_position(residual_position),
            )
        )

    return IntegrityReport(
        stage="POST_RENDER",
        passed=not any(issue.severity == "ERROR" for issue in issues),
        checked_units=len(expected),
        chapters_checked=len({unit.chapter_id for unit in expected}),
        issues=issues,
    )


def pdf_body_start_page_index(pdf_path: str | Path) -> int:
    """Return the zero-based first bookmarked body page, after title/TOC pages."""
    generated_front_matter = {
        "contents",
        "reference information",
        "reference source",
    }
    with pymupdf.open(pdf_path) as document:
        for _level, title, page_number, *_rest in document.get_toc(simple=True):
            if normalize_integrity_text(title).casefold() not in generated_front_matter:
                return max(0, int(page_number) - 1)
    return 0
