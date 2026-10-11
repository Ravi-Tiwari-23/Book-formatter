from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from .matching import normalize_text
from .models import BookSection


_NUMBERED = re.compile(
    r"^(?:(?:remedy|remedies)\s*)?(\d{1,2})\s*[.)\-:]\s*(.+)$", re.IGNORECASE
)
_NUMBER_ONLY = re.compile(r"^(?:remedy\s*)?(\d{1,2})\s*[.)\-:]?$", re.IGNORECASE)
_INLINE_NUMBERED = re.compile(r"(?<!\w)(\d{1,2})\s*[.)]\s+")


@dataclass(slots=True)
class SectionMatch:
    source: BookSection
    reference: BookSection | None
    score: float
    matched_by: str


@dataclass(slots=True)
class DocumentSections:
    remedies: list[BookSection]
    front_matter: list[BookSection]


def normalize_title(title: str) -> str:
    value = normalize_text(title).casefold()
    value = re.sub(r"[^\w\u0900-\u097f ]+", "", value)
    return re.sub(r"\s+", " ", value).strip()


def _split_numbered_fragments(line: str) -> list[str]:
    matches = list(_INLINE_NUMBERED.finditer(line))
    if not matches:
        return [line]
    fragments: list[str] = []
    if matches[0].start() > 0:
        prefix = line[: matches[0].start()].strip()
        if prefix:
            fragments.append(prefix)
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(line)
        fragment = line[match.start():end].strip()
        if fragment:
            fragments.append(fragment)
    return fragments


def _reflow_paragraphs(values: list[str], is_noise) -> list[str]:
    paragraphs: list[str] = []
    current: list[str] = []
    for value in values:
        if not value:
            if current:
                paragraphs.append(normalize_text(" ".join(current)))
                current = []
            continue
        if is_noise(value):
            continue
        current.append(value)
    if current:
        paragraphs.append(normalize_text(" ".join(current)))
    return [paragraph for paragraph in paragraphs if paragraph]


def _is_doubled_artifact(value: str) -> bool:
    compact = value.strip().casefold()
    midpoint = len(compact) // 2
    if len(compact) >= 12 and len(compact) % 2 == 0 and compact[:midpoint] == compact[midpoint:]:
        return True
    tokens = compact.split()
    return bool(tokens) and all(
        len(token) >= 2
        and len(token) % 2 == 0
        and token[: len(token) // 2] == token[len(token) // 2 :]
        for token in tokens
    )


def detect_sections(pages: list[tuple[int, str]], *, maximum_number: int = 99) -> list[BookSection]:
    sections: list[BookSection] = []
    current: dict | None = None
    pending_number: tuple[int, int] | None = None

    def finish() -> None:
        nonlocal current
        if not current:
            return
        raw = "\n".join(current["body"]).strip()
        paragraphs = [normalize_text(part) for part in re.split(r"\n\s*\n|\n", raw) if normalize_text(part)]
        sections.append(
            BookSection(
                current["number"],
                current["title"],
                paragraphs,
                current["page_start"],
                current["page_end"],
                raw_text=raw,
                normalized_text=normalize_text(raw),
            )
        )
        current = None

    for page_number, text in pages:
        for line in text.splitlines():
            clean = normalize_text(line)
            if not clean:
                if current:
                    current["body"].append("")
                continue
            if pending_number:
                number, start_page = pending_number
                finish()
                current = {
                    "number": number,
                    "title": clean,
                    "body": [],
                    "page_start": start_page,
                    "page_end": page_number,
                }
                pending_number = None
                continue
            match = _NUMBERED.match(clean)
            if match and 1 <= int(match.group(1)) <= maximum_number:
                finish()
                current = {
                    "number": int(match.group(1)),
                    "title": match.group(2).strip(),
                    "body": [],
                    "page_start": page_number,
                    "page_end": page_number,
                }
                continue
            number_only = _NUMBER_ONLY.match(clean)
            if number_only and 1 <= int(number_only.group(1)) <= maximum_number:
                pending_number = (int(number_only.group(1)), page_number)
                continue
            if current:
                current["body"].append(clean)
                current["page_end"] = page_number
    finish()
    return sections


def detect_document_sections(
    pages: list[tuple[int, str]], *, expected_remedies: int | None = None
) -> DocumentSections:
    """Detect the canonical numbered remedy run and keep preceding matter separate."""
    lines: list[tuple[int, str]] = []
    contents_pages: set[int] = set()
    page_occurrences: dict[str, set[int]] = {}
    for page_number, text in pages:
        original_lines = [normalize_text(line) for line in text.splitlines()]
        if any(
            line.casefold() in {"contents", "table of contents", "index"}
            for line in original_lines if line
        ):
            contents_pages.add(page_number)
        for original_line in original_lines:
            if not original_line:
                lines.append((page_number, ""))
                continue
            for line in _split_numbered_fragments(original_line):
                lines.append((page_number, line))
                page_occurrences.setdefault(line.casefold(), set()).add(page_number)
        lines.append((page_number, ""))

    if expected_remedies is None:
        observed = [int(m.group(1)) for _, line in lines if (m := _NUMBERED.match(line))]
        expected_remedies = max(observed, default=99)
    candidates: list[tuple[int, str, int, int]] = []
    for index, (page_number, line) in enumerate(lines):
        if page_number in contents_pages:
            continue
        match = _NUMBERED.match(line)
        if match and 1 <= int(match.group(1)) <= expected_remedies:
            candidates.append((int(match.group(1)), match.group(2).strip(), page_number, index))
            continue
        number_only = _NUMBER_ONLY.match(line)
        if number_only and 1 <= int(number_only.group(1)) <= expected_remedies:
            title = lines[index + 1][1] if index + 1 < len(lines) else ""
            candidates.append((int(number_only.group(1)), title, page_number, index))

    selected: list[tuple[int, str, int, int]] = []
    for start, candidate in enumerate(candidates):
        if candidate[0] != 1:
            continue
        run = [candidate]
        expected = 2
        for later in candidates[start + 1:]:
            if later[0] == expected:
                run.append(later)
                expected += 1
                if expected > expected_remedies:
                    break
        if len(run) == expected_remedies:
            selected = run
            break

    if not selected:
        return DocumentSections(detect_sections(pages, maximum_number=expected_remedies), [])

    repeated_noise = {
        text
        for text, page_numbers in page_occurrences.items()
        if len(page_numbers) >= 3 and len(text) <= 80
    }

    def is_noise(text: str) -> bool:
        folded = text.casefold().strip()
        return (
            folded in repeated_noise
            or _is_doubled_artifact(text)
            or folded in {"trueloger.com", "truelogger.com"}
            or bool(re.fullmatch(r"truelogg?er\.com\s+\d{1,3}", folded))
            or bool(re.fullmatch(r"(?:page\s*)?\d{1,3}", folded))
        )

    remedies: list[BookSection] = []
    for selected_index, (number, title, page_start, line_index) in enumerate(selected):
        next_index = (
            selected[selected_index + 1][3]
            if selected_index + 1 < len(selected)
            else len(lines)
        )
        body = _reflow_paragraphs(
            [text for _, text in lines[line_index + 1:next_index]], is_noise
        )
        page_end = lines[next_index - 1][0] if next_index > line_index + 1 else page_start
        raw = "\n".join(body).strip()
        remedies.append(
            BookSection(
                number,
                title,
                body,
                page_start,
                page_end,
                raw_text=raw,
                normalized_text=normalize_text(raw),
            )
        )

    front_lines = _reflow_paragraphs(
        [text for _, text in lines[: selected[0][3]]], is_noise
    )
    front_matter = []
    if front_lines:
        raw = "\n".join(front_lines)
        front_matter.append(
            BookSection(
                None,
                "Front Matter",
                front_lines,
                lines[0][0],
                selected[0][2],
                raw_text=raw,
                normalized_text=normalize_text(raw),
            )
        )
    return DocumentSections(remedies, front_matter)


def align_sections(
    source: list[BookSection], reference: list[BookSection], *, match_numbers: bool = True
) -> list[SectionMatch]:
    by_number = {section.number: section for section in reference if section.number is not None}
    used: set[int] = set()
    result: list[SectionMatch] = []
    for source_section in source:
        if match_numbers and source_section.number in by_number:
            candidate = by_number[source_section.number]
            used.add(id(candidate))
            score = fuzz.WRatio(normalize_title(source_section.title), normalize_title(candidate.title))
            result.append(SectionMatch(source_section, candidate, float(score), "number"))
            continue
        available = [item for item in reference if id(item) not in used]
        if not available:
            result.append(SectionMatch(source_section, None, 0, "unmatched"))
            continue
        def similarity(item):
            title = normalize_title(source_section.title)
            candidate_title = normalize_title(item.title)
            if title and candidate_title:
                return fuzz.WRatio(title, candidate_title)
            return fuzz.ratio(' '.join(source_section.paragraphs), ' '.join(item.paragraphs))

        candidate = max(
            available,
            key=similarity,
        )
        score = similarity(candidate)
        if score >= 75:
            used.add(id(candidate))
            result.append(SectionMatch(source_section, candidate, float(score), "title"))
        else:
            result.append(SectionMatch(source_section, None, float(score), "unmatched"))
    return result

