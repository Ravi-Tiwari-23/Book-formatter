from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any

import pymupdf

from .config import load_book_style
from .models import BlockKind, StructuredBlock


def _configure_weasyprint_dlls() -> str | None:
    configured = os.environ.get("WEASYPRINT_DLL_DIRECTORIES")
    if configured:
        return configured
    candidates = [
        os.environ.get("TRUELOGGER_GTK_BIN"),
        r"C:\msys64-truelogger\ucrt64\bin",
        r"C:\msys64\ucrt64\bin",
    ]
    for candidate in candidates:
        if candidate and Path(candidate, "libgobject-2.0-0.dll").exists():
            os.environ["WEASYPRINT_DLL_DIRECTORIES"] = candidate
            return candidate
    return None


_configure_weasyprint_dlls()


def _slug(text: str, index: int) -> str:
    slug = re.sub(r"[^\w\u0900-\u097f]+", "-", text.casefold()).strip("-")
    return f"{slug or 'section'}-{index}"


def _block_html(block: StructuredBlock, index: int) -> tuple[str, str | None]:
    text = html.escape(block.text).replace("\n", "<br>")
    anchor = _slug(block.text, index)
    if block.kind == BlockKind.BOOK_TITLE:
        return f'<h1 class="book-title" id="{anchor}">{text}</h1>', None
    if block.kind == BlockKind.CHAPTER or (block.kind == BlockKind.MAJOR_SECTION and block.start_new_page):
        return f'<h1 class="chapter" id="{anchor}">{text}</h1>', anchor
    if block.kind in {BlockKind.HEADING, BlockKind.SECTION, BlockKind.MAJOR_SECTION}:
        return f'<h2 id="{anchor}">{text}</h2>', anchor
    if block.kind in {BlockKind.SUBHEADING, BlockKind.SUBSECTION}:
        return f'<h3 id="{anchor}">{text}</h3>', anchor
    if block.kind == BlockKind.VERSE:
        return f'<div class="verse">{text}</div>', None
    if block.kind == BlockKind.QUOTE:
        return f"<blockquote>{text}</blockquote>", None
    if block.kind in {BlockKind.LIST, BlockKind.BULLET_LIST}:
        return f'<p class="list-item">{text}</p>', None
    if block.kind == BlockKind.TABLE and block.table_rows:
        rows = ''.join('<tr>' + ''.join(f'<td>{html.escape(cell)}</td>' for cell in row) + '</tr>' for row in block.table_rows)
        return f'<table class="source-table"><tbody>{rows}</tbody></table>', None
    if block.kind == BlockKind.IMAGE and block.image_path:
        source = Path(block.image_path).resolve().as_uri()
        return (
            f'<figure><img src="{source}" alt="{text}"><figcaption>{text}</figcaption></figure>',
            None,
        )
    if block.kind == BlockKind.REFERENCE_INFO:
        rows: list[str] = []
        for line in block.text.splitlines()[1:]:
            label, separator, value = line.partition(":")
            if separator:
                rows.append(
                    f"<div class=\"reference-row\"><dt>{html.escape(label)}</dt>"
                    f"<dd>{html.escape(value.strip())}</dd></div>"
                )
        return (
            '<section class="reference-info"><p class="eyebrow">Reference source</p>'
            f'<h1>Reference information</h1><dl>{"".join(rows)}</dl></section>',
            None,
        )
    if block.kind == BlockKind.REMEDY:
        number, _, title = block.text.partition("\n")
        return (
            f'<section class="remedy" id="{anchor}"><span class="remedy-number">{html.escape(number)}</span><h2>{html.escape(title or number)}</h2></section>',
            anchor,
        )
    return f"<p>{text}</p>", None


def _remedy_parts(text: str) -> tuple[str, str]:
    number, separator, title = text.partition("\n")
    if separator:
        return number.strip(), title.strip()
    match = re.match(r"^(\d{1,3})\s*[.)\-:]?\s+(.+)$", text.strip())
    if match:
        return match.group(1), match.group(2)
    return "", text.strip()


def _toc_row(anchor: str, label: str, level: int) -> str:
    number, title = _remedy_parts(label) if level == 3 else ("", label.replace("\n", " "))
    return (
        f'<li class="toc-row level-{level}"><a href="#{anchor}">'
        f'<span class="toc-number">{html.escape(number)}</span>'
        f'<span class="toc-title">{html.escape(title)}</span>'
        '<span class="toc-leader" aria-hidden="true"></span></a></li>'
    )


def _render_main_content(
    blocks: list[StructuredBlock], style: dict[str, Any]
) -> tuple[str, list[tuple[str, str, int]]]:
    rendered: list[str] = []
    toc: list[tuple[str, str, int]] = []
    index = 0
    while index < len(blocks):
        block = blocks[index]
        if block.kind not in {BlockKind.REMEDY, BlockKind.NUMBERED_ITEM}:
            fragment, anchor = _block_html(block, index)
            rendered.append(fragment)
            if anchor and block.include_in_toc:
                toc.append((anchor, block.text, block.level or 1))
            index += 1
            continue

        anchor = _slug(block.text, index)
        number, title = _remedy_parts(block.text)
        children: list[tuple[int, StructuredBlock]] = []
        next_index = index + 1
        boundaries = {
            BlockKind.REMEDY,
            BlockKind.CHAPTER,
            BlockKind.HEADING,
            BlockKind.SUBHEADING,
            BlockKind.REFERENCE_INFO,
            BlockKind.BOOK_TITLE,
            BlockKind.NUMBERED_ITEM,
            BlockKind.MAJOR_SECTION,
            BlockKind.SECTION,
            BlockKind.SUBSECTION,
        }
        while next_index < len(blocks) and blocks[next_index].kind not in boundaries:
            children.append((next_index, blocks[next_index]))
            next_index += 1

        opening_child = children[0] if children and children[0][1].kind in {BlockKind.BODY, BlockKind.BODY_PARAGRAPH} else None
        total_characters = len(block.text) + sum(len(child.text) for _, child in children)
        short_class = (
            " short-remedy"
            if total_characters <= int(style.get("short_remedy_max_characters", 950))
            and len(children) <= 5
            else ""
        )
        header = (
            '<header class="remedy-heading">'
            f'<span class="remedy-number">{html.escape(number)}</span>'
            f'<h2>{html.escape(title or number)}</h2></header>'
        )
        opening = header
        if opening_child:
            opening_fragment, _ = _block_html(opening_child[1], opening_child[0])
            opening += opening_fragment.replace("<p>", '<p class="first-paragraph">', 1)
        contents: list[str] = []
        for child_index, child in children:
            if opening_child and child_index == opening_child[0]:
                continue
            fragment, _ = _block_html(child, child_index)
            contents.append(fragment)
        rendered.append(
            f'<section class="remedy{short_class}" id="{anchor}">'
            f'<div class="remedy-opening">{opening}</div>{"".join(contents)}</section>'
        )
        if block.include_in_toc:
            toc.append((anchor, block.text, 3))
        index = next_index
    return "\n".join(rendered), toc


def build_book_html(
    blocks: list[StructuredBlock],
    style: dict[str, Any] | None = None,
    *,
    include_title_page: bool = True,
    protected_placeholder_count: int = 0,
) -> str:
    style = style or load_book_style()
    front_blocks = [block for block in blocks if block.kind == BlockKind.REFERENCE_INFO]
    main_blocks = [
        block
        for block in blocks
        if block.kind not in {BlockKind.BOOK_TITLE, BlockKind.REFERENCE_INFO}
    ]
    body, toc = _render_main_content(main_blocks, style)
    toc_html = "".join(_toc_row(anchor, label, level) for anchor, label, level in toc)
    front_html = "".join(_block_html(block, index)[0] for index, block in enumerate(front_blocks))
    body_stack = (
        f"'{style['body_font']}', 'Book Devanagari', '{style.get('devanagari_font', 'Nirmala UI')}', "
        "'Noto Serif Devanagari', serif"
    )
    heading_stack = (
        f"'{style['heading_font']}', 'Book Devanagari', '{style.get('devanagari_font', 'Nirmala UI')}', "
        "'Noto Serif Devanagari', serif"
    )
    if style.get('language') in {'hindi', 'mixed', 'hi'}:
        body_stack = "'Book Devanagari', " + body_stack
        heading_stack = "'Book Devanagari', " + heading_stack
    # Use the font's real family name: Fontconfig's file-name aliases are not
    # consistently applied on Windows.
    body_stack = body_stack.replace('Book Devanagari', 'Noto Serif Devanagari')
    heading_stack = heading_stack.replace('Book Devanagari', 'Noto Serif Devanagari')
    devanagari_font = (Path(__file__).resolve().parents[2] / "assets/fonts/NotoSerifDevanagari.ttf").as_uri()
    css = f"""
      @font-face {{ font-family: 'Noto Serif Devanagari'; src: url('{devanagari_font}'); font-weight: normal; }}
      @page {{ size: {style['page_size']}; margin: {style['margin_top_mm']}mm {style['margin_right_mm']}mm {style['margin_bottom_mm']}mm {style['margin_left_mm']}mm;
        @bottom-center {{ content: counter(page); font-size: 8pt; color: #666; }} }}
      @page:first {{ @bottom-center {{ content: none; }} }}
      * {{ box-sizing: border-box; }}
      html {{ font-family: {body_stack}; color: {style['text_color']}; }}
      body {{ font-size: {style['body_size_pt']}pt; line-height: {style['line_height']}; text-align: justify; }}
      .title-page {{ page-break-after: always; min-height: 155mm; display: flex; align-items: center; justify-content: center; text-align: center; }}
      .protected-placeholder {{ page-break-after: always; min-height: 155mm; }}
      h1, h2, h3 {{ font-family: {heading_stack}; }}
      .title-page .book-title {{ font-size: {style['book_title_size_pt']}pt; color: {style['accent_color']}; bookmark-level: none; letter-spacing: .02em; }}
      .reference-info {{ page-break-after: always; padding-top: 18mm; text-align: left; }}
      .reference-info .eyebrow {{ color: {style['accent_color']}; font-size: 8pt; font-weight: 700; letter-spacing: .16em; text-transform: uppercase; }}
      .reference-info h1 {{ color: {style['accent_color']}; font-size: 20pt; margin: .25em 0 1.4em; }}
      .reference-info dl {{ margin: 0; }}
      .reference-row {{ display: grid; grid-template-columns: 31mm 1fr; gap: 5mm; border-top: .35pt solid #dfd5c9; padding: 3.5mm 0; break-inside: avoid; }}
      .reference-row dt {{ color: #6d6258; font-size: 8.5pt; text-transform: uppercase; letter-spacing: .05em; }}
      .reference-row dd {{ margin: 0; text-align: left; }}
      .contents {{ page-break-after: always; }}
      .contents h1 {{ color: {style['accent_color']}; font-size: 21pt; margin-bottom: 1em; }}
      .contents ol {{ margin: 0; padding: 0; }}
      .toc-row {{ list-style: none; margin: 0 0 2.4mm; font-size: {style.get('toc_size_pt', 9.25)}pt; line-height: 1.25; break-inside: avoid; }}
      .toc-row.level-2 {{ margin-left: 5mm; }}
      .toc-row.level-3 {{ margin-left: 9mm; }}
      .toc-row a {{ display: grid; grid-template-columns: 9mm minmax(38mm, auto) minmax(8mm, 1fr) auto; column-gap: 2mm; align-items: end; color: inherit; text-decoration: none; }}
      .toc-row a::after {{ content: target-counter(attr(href), page); grid-column: 4; min-width: 7mm; text-align: right; font-variant-numeric: tabular-nums; }}
      .toc-number {{ grid-column: 1; color: {style['accent_color']}; font-variant-numeric: tabular-nums; }}
      .toc-title {{ grid-column: 2; text-align: left; overflow-wrap: anywhere; }}
      .toc-leader {{ grid-column: 3; border-bottom: .6pt dotted #9a8c7e; margin-bottom: .28em; }}
      .chapter {{ page-break-before: always; padding-top: 24mm; margin: 0 0 10mm; font-size: {style['chapter_size_pt']}pt; line-height: 1.18; text-align: center; color: {style['accent_color']}; break-after: avoid; }}
      h2 {{ font-size: {style['heading_size_pt']}pt; color: {style['accent_color']}; break-after: avoid; page-break-after: avoid; }}
      h3 {{ font-size: {style['subheading_size_pt']}pt; break-after: avoid; page-break-after: avoid; }}
      .remedy {{ margin-top: 5.2mm; }}
      .remedy.short-remedy {{ break-inside: avoid; page-break-inside: avoid; }}
      .remedy-opening {{ break-inside: avoid; page-break-inside: avoid; }}
      .remedy-heading {{ break-after: avoid; page-break-after: avoid; }}
      .remedy-number {{ display: block; font-size: 9pt; letter-spacing: .16em; color: {style['accent_color']}; }}
      .remedy h2 {{ margin: .12em 0 .55em; font-size: {style.get('remedy_title_size_pt', 12.5)}pt; line-height: 1.22; text-align: left; }}
      .first-paragraph {{ orphans: 3; widows: 3; }}
      p {{ margin: 0 0 {style.get('paragraph_spacing_pt', 6)}pt; orphans: 3; widows: 3; }}
      .source-table {{ border-collapse: collapse; width: 100%; margin: 5mm 0; text-align: left; font-size: 9.5pt; }}
      .source-table td {{ border: .5pt solid #aaa; padding: 2mm; overflow-wrap: anywhere; }}
      .source-table tr {{ break-inside: avoid; }}
      .verse {{ margin: 1.2em 8%; text-align: center; white-space: normal; break-inside: avoid; }}
      blockquote {{ margin: 1em 8%; font-style: italic; }}
      figure {{ margin: 3mm auto 4mm; text-align: center; break-inside: avoid; page-break-inside: avoid; }}
      figure img {{ display: block; width: auto; height: auto; max-width: {style.get('image_max_width_percent', 82)}%; max-height: {style.get('image_max_height_mm', 118)}mm; margin: 0 auto; object-fit: contain; }}
      figcaption {{ margin-top: 1.5mm; font-size: {style.get('caption_size_pt', 8)}pt; line-height: 1.2; color: #766f69; text-align: center; }}
    """
    title = next((b.text for b in blocks if b.kind == BlockKind.BOOK_TITLE), "Book")
    if protected_placeholder_count:
        title_html = "".join(
            '<section class="protected-placeholder"></section>'
            for _ in range(protected_placeholder_count)
        )
    else:
        title_html = (
            f'<section class="title-page"><h1 class="book-title">{html.escape(title)}</h1></section>'
            if include_title_page
            else ""
        )
    contents_html = f'<nav class="contents"><h1>Contents</h1><ol>{toc_html}</ol></nav>' if toc else ''
    return f"""<!doctype html><html lang="{style.get('language', 'en')}"><head><meta charset="utf-8"><title>{html.escape(title)}</title><style>{css}</style></head>
    <body>{title_html}{front_html}{contents_html}<main style="bookmark-level: 1; bookmark-label: 'Document content'">{body}</main></body></html>"""


def render_book(
    blocks: list[StructuredBlock],
    output_path: str | Path,
    *,
    style: dict[str, Any] | None = None,
    include_title_page: bool = True,
    protected_placeholder_count: int = 0,
) -> Path:
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        from weasyprint import HTML
        from .rendering_unicode import install

        install()

        HTML(
            string=build_book_html(
                blocks,
                style,
                include_title_page=include_title_page,
                protected_placeholder_count=protected_placeholder_count,
            ),
            base_url=str(target.parent),
        ).write_pdf(target)
    except OSError as error:
        if "libgobject" not in str(error).casefold():
            raise
        if style and style.get('page_dimensions_pt'):
            raise RuntimeError('Adaptive export requires the WeasyPrint rendering libraries. '
                               'Install/configure GTK before building this document.') from error
        _render_pymupdf_fallback(
            blocks,
            target,
            style or load_book_style(),
            include_title_page=include_title_page,
            protected_placeholder_count=protected_placeholder_count,
        )
    return target


def weasyprint_available() -> tuple[bool, str | None]:
    try:
        from weasyprint import HTML  # noqa: F401
    except (ImportError, OSError) as error:
        return False, str(error)
    return True, None


def _render_pymupdf_fallback(
    blocks: list[StructuredBlock],
    target: Path,
    style: dict[str, Any],
    *,
    include_title_page: bool = True,
    protected_placeholder_count: int = 0,
) -> None:
    """Portable Windows fallback used only when WeasyPrint's GTK stack is absent."""
    document = pymupdf.open()
    page_width, page_height = pymupdf.paper_size(style.get("page_size", "A5"))
    margin = 48

    title = next((block.text for block in blocks if block.kind == BlockKind.BOOK_TITLE), "Book")
    if protected_placeholder_count:
        for _ in range(protected_placeholder_count):
            document.new_page(width=page_width, height=page_height)
    elif include_title_page:
        title_page = document.new_page(width=page_width, height=page_height)
        title_page.insert_htmlbox(
            pymupdf.Rect(margin, page_height * 0.32, page_width - margin, page_height * 0.72),
            f"<h1>{html.escape(title)}</h1>",
            css=f"* {{font-family: sans-serif; text-align:center; color:{style['accent_color']};}} h1{{font-size:24pt;}}",
        )

    headings = [
        (block, index)
        for index, block in enumerate(blocks)
        if block.kind in {BlockKind.CHAPTER, BlockKind.HEADING, BlockKind.SUBHEADING, BlockKind.REMEDY}
    ]
    toc_page = document.new_page(width=page_width, height=page_height)
    toc_rows = "".join(f"<p>{html.escape(block.text)}</p>" for block, _ in headings)
    toc_page.insert_htmlbox(
        pymupdf.Rect(margin, margin, page_width - margin, page_height - margin),
        f"<h1>Contents</h1>{toc_rows}",
        css="*{font-family:sans-serif;} h1{font-size:20pt;} p{font-size:10pt;}",
    )

    toc: list[list[Any]] = []
    current_page = None
    current_number = len(document)
    y = margin
    for block in blocks:
        if block.kind == BlockKind.BOOK_TITLE:
            continue
        is_chapter = block.kind == BlockKind.CHAPTER
        if current_page is None or (is_chapter and y > margin):
            current_page = document.new_page(width=page_width, height=page_height)
            current_number = len(document)
            y = margin
        sizes = {
            BlockKind.CHAPTER: 19,
            BlockKind.HEADING: 15,
            BlockKind.SUBHEADING: 12,
            BlockKind.VERSE: 11,
            BlockKind.REMEDY: 15,
        }
        size = sizes.get(block.kind, style.get("body_size_pt", 10.5))
        estimated = max(42, (len(block.text) // 45 + 1) * (float(size) * 1.6))
        if y + estimated > page_height - 58:
            current_page = document.new_page(width=page_width, height=page_height)
            current_number = len(document)
            y = margin
        if block.kind == BlockKind.IMAGE and block.image_path:
            image_rect = pymupdf.Rect(margin, y, page_width - margin, min(page_height - 48, y + 220))
            current_page.insert_image(image_rect, filename=block.image_path, keep_proportion=True)
            y += 230
            continue
        tag = "h1" if block.kind == BlockKind.CHAPTER else "h2" if block.kind in {BlockKind.HEADING, BlockKind.SUBHEADING, BlockKind.REMEDY} else "div"
        align = "center" if block.kind == BlockKind.VERSE else "justify"
        current_page.insert_htmlbox(
            pymupdf.Rect(margin, y, page_width - margin, min(page_height - 48, y + estimated)),
            f"<{tag}>{html.escape(block.text).replace(chr(10), '<br>')}</{tag}>",
            css=f"*{{font-family:sans-serif;font-size:{size}pt;line-height:1.45;text-align:{align};}} h1,h2{{color:{style['accent_color']};}}",
        )
        if block.kind in {BlockKind.CHAPTER, BlockKind.HEADING, BlockKind.SUBHEADING, BlockKind.REMEDY}:
            level = 1 if block.kind in {BlockKind.CHAPTER, BlockKind.REMEDY} else 2 if block.kind == BlockKind.HEADING else 3
            toc.append([level, block.text, current_number])
        y += estimated + 7

    for number, page in enumerate(document, start=1):
        if number > 1:
            page.insert_text(
                pymupdf.Point(page_width / 2 - 4, page_height - 20), str(number), fontsize=8, color=(0.4, 0.4, 0.4)
            )
    document.set_toc(toc)
    document.save(target, garbage=4, deflate=True)
    document.close()

