from __future__ import annotations

import html
import os
import re
from pathlib import Path
from typing import Any

import pymupdf

from .config import load_book_style
from .models import BlockKind, StructuredBlock
from .theme import BookTheme


def _configure_weasyprint_dlls() -> str | None:
    configured = os.environ.get("WEASYPRINT_DLL_DIRECTORIES")
    if configured:
        return configured
    candidates = [
        os.environ.get("BOOKLOOM_GTK_BIN"),
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
    style = style or BookTheme.load().to_style()
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
      @page {{ size: A4; margin: {style['margin_top_mm']}mm {style['margin_right_mm']}mm {style['margin_bottom_mm']}mm {style['margin_left_mm']}mm;
        @bottom-center {{ content: counter(page); font-size: 8pt; color: {style.get('muted_color', '#687875')}; border-top: .45pt solid {style.get('rule_color', '#A8BFBA')}; padding-top: 2mm; width: 100%; text-align: center; }} }}
      @page cover {{ size: A4; margin: 0; background: {style.get('cover_color', '#154A46')}; @bottom-center {{ content: none; border: 0; }} }}
      * {{ box-sizing: border-box; }}
      html {{ font-family: {body_stack}; color: {style['text_color']}; }}
      body {{ font-size: {style['body_size_pt']}pt; line-height: {style['line_height']}; text-align: justify; }}
      .title-page {{ page: cover; position: relative; page-break-after: always; height: 297mm; padding: 24mm; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; color: {style.get('cover_text_color', '#F7FAF8')}; background: {style.get('cover_color', '#154A46')}; }}
      .protected-placeholder {{ page-break-after: always; min-height: 155mm; }}
      h1, h2, h3 {{ font-family: {heading_stack}; }}
      .cover-kicker {{ margin: 0 0 12mm; font-size: 9pt; font-weight: 700; letter-spacing: .22em; }}
      .title-page .book-title {{ max-width: 150mm; margin: 0; font-size: {style['book_title_size_pt']}pt; color: {style.get('cover_text_color', '#F7FAF8')}; bookmark-level: none; letter-spacing: .01em; line-height: 1.16; }}
      .cover-author {{ margin-top: 9mm; font-size: 12pt; }}
      .cover-publisher {{ position: absolute; left: 0; right: 0; bottom: 20mm; text-align: center; font-size: 8.5pt; font-weight: 700; letter-spacing: .18em; }}
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
      .chapter {{ page-break-before: always; padding-top: {style.get('chapter_padding_top_mm', 8)}mm; margin: 0 0 9mm; font-size: {style['chapter_size_pt']}pt; line-height: 1.18; text-align: left; color: {style['accent_color']}; break-after: avoid; page-break-after: avoid; }}
      h2 {{ margin: 5mm 0 2.5mm; font-size: {style['heading_size_pt']}pt; color: {style['accent_color']}; break-after: avoid; page-break-after: avoid; }}
      h3 {{ margin: 4mm 0 2mm; font-size: {style['subheading_size_pt']}pt; break-after: avoid; page-break-after: avoid; }}
      .remedy {{ margin-top: 5.2mm; }}
      .remedy.short-remedy {{ break-inside: avoid; page-break-inside: avoid; }}
      .remedy-opening {{ break-inside: avoid; page-break-inside: avoid; }}
      .remedy-heading {{ break-after: avoid; page-break-after: avoid; }}
      .remedy-number {{ display: block; font-size: 9pt; letter-spacing: .16em; color: {style['accent_color']}; }}
      .remedy h2 {{ margin: .12em 0 .55em; font-size: {style.get('remedy_title_size_pt', 12.5)}pt; line-height: 1.22; text-align: left; }}
      .first-paragraph {{ orphans: 3; widows: 3; }}
      p {{ margin: 0 0 {style.get('paragraph_spacing_pt', 6)}pt; orphans: 3; widows: 3; }}
      .source-table {{ border-collapse: collapse; width: 100%; margin: 5mm 0; text-align: left; font-size: 9.5pt; }}
      .source-table td {{ border: .5pt solid {style.get('rule_color', '#A8BFBA')}; padding: 2mm; overflow-wrap: anywhere; }}
      .source-table tr:nth-child(odd) {{ background: #F2F6F4; }}
      .list-item {{ position: relative; padding-left: 5mm; text-align: left; }}
      .source-table tr {{ break-inside: avoid; }}
      .verse {{ margin: 1.2em 8%; text-align: center; white-space: normal; break-inside: avoid; }}
      blockquote {{ margin: 1em 8%; font-style: italic; }}
      figure {{ margin: 3mm auto 4mm; text-align: center; break-inside: avoid; page-break-inside: avoid; }}
      figure img {{ display: block; width: auto; height: auto; max-width: {style.get('image_max_width_percent', 82)}%; max-height: {style.get('image_max_height_mm', 118)}mm; margin: 0 auto; object-fit: contain; }}
      figcaption {{ margin-top: 1.5mm; font-size: {style.get('caption_size_pt', 8)}pt; line-height: 1.2; color: #766f69; text-align: center; }}
    """
    title = next((b.text for b in blocks if b.kind == BlockKind.BOOK_TITLE), "Book")
    metadata = style.get("metadata") or {}
    author = metadata.get("author")
    publisher = metadata.get("publisher") or style.get("publisher_brand", "TRUELOGER")
    cover_meta_html = (
        (f'<p class="cover-author">{html.escape(author)}</p>' if author else "")
        + (f'<p class="cover-publisher">{html.escape(publisher)}</p>' if publisher else "")
    )
    if protected_placeholder_count:
        title_html = "".join(
            '<section class="protected-placeholder"></section>'
            for _ in range(protected_placeholder_count)
        )
    else:
        title_html = (
            '<section class="title-page collection-cover">'
            '<p class="cover-kicker">READING EDITION</p>'
            f'<h1 class="book-title">{html.escape(title)}</h1>{cover_meta_html}</section>'
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
    production: bool = False,
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
        if production:
            raise RuntimeError(
                "Final production requires WeasyPrint with GTK/Pango. Configure BOOKLOOM_GTK_BIN, then retry."
            ) from error
        _render_pymupdf_fallback(
            blocks,
            target,
            style or BookTheme.load().to_style(),
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
    page_width, page_height = pymupdf.paper_size("A4")
    margin = float(style.get("margin_left_mm", 18)) * 72 / 25.4

    title = next((block.text for block in blocks if block.kind == BlockKind.BOOK_TITLE), "Book")
    if protected_placeholder_count:
        for _ in range(protected_placeholder_count):
            document.new_page(width=page_width, height=page_height)
    elif include_title_page:
        title_page = document.new_page(width=page_width, height=page_height)
        title_page.draw_rect(
            title_page.rect,
            color=_hex_rgb(style.get("cover_color", "#154A46")),
            fill=_hex_rgb(style.get("cover_color", "#154A46")),
        )
        metadata = style.get("metadata") or {}
        author = metadata.get("author") or ""
        publisher = metadata.get("publisher") or style.get("publisher_brand", "TRUELOGER")
        title_page.insert_htmlbox(
            pymupdf.Rect(margin, page_height * 0.32, page_width - margin, page_height * 0.72),
            f"<p>READING EDITION</p><h1>{html.escape(title)}</h1><h2>{html.escape(author)}</h2><p>{html.escape(publisher)}</p>",
            css="* {font-family: serif; text-align:center; color:#F7FAF8;} h1{font-size:28pt;} h2{font-size:12pt;} p{font-size:9pt;letter-spacing:2px;}",
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
            y = (
                (float(style.get("margin_top_mm", 16)) + float(style.get("chapter_padding_top_mm", 8))) * 72 / 25.4
                if is_chapter
                else float(style.get("margin_top_mm", 16)) * 72 / 25.4
            )
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
            footer_y = page_height - 28
            page.draw_line(
                pymupdf.Point(margin, footer_y - 8),
                pymupdf.Point(page_width - margin, footer_y - 8),
                color=_hex_rgb(style.get("rule_color", "#A8BFBA")),
                width=0.45,
            )
            page.insert_text(
                pymupdf.Point(page_width / 2 - 4, footer_y), str(number), fontsize=8, color=(0.4, 0.4, 0.4)
            )
    document.set_toc(toc)
    document.save(target, garbage=4, deflate=True)
    document.close()


def _hex_rgb(value: str) -> tuple[float, float, float]:
    value = value.lstrip("#")
    return tuple(int(value[index:index + 2], 16) / 255 for index in (0, 2, 4))

