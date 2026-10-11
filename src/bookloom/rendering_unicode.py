"""WeasyPrint compatibility for context-dependent shaped Unicode clusters.

The same glyph may represent different Unicode clusters in Indic scripts.
A font-wide ToUnicode map cannot express those per-occurrence differences.
PDF ActualText records the logical text of each *rendered line*, alongside
its normal visible glyphs. It is not reconstructed from approved text.
"""
from functools import wraps

import pydyf
import weasyprint.draw as drawing


def install() -> None:
    original = drawing.draw_text
    if getattr(original, '_bookloom_actual_text', False):
        return

    @wraps(original)
    def draw_line(stream, textbox, offset_x, text_overflow, block_ellipsis='none'):
        # Do not describe undisplayed text when a caller requests ellipsizing.
        use_actual = (any('\u0900' <= c <= '\u097f' for c in textbox.text)
                      and text_overflow != 'ellipsis' and block_ellipsis == 'none')
        if use_actual:
            stream.begin_marked_content('Span', pydyf.Dictionary({
                'ActualText': pydyf.String(textbox.text),
            }))
        show_text = stream.show_text
        if use_actual:
            # Empty TJ strings emitted around positioned marks cause some
            # readers to terminate ActualText early. Numeric advances remain.
            stream.show_text = lambda value: show_text(value.replace('<>', ''))
        try:
            return original(stream, textbox, offset_x, text_overflow, block_ellipsis)
        finally:
            stream.show_text = show_text
            if use_actual:
                stream.end_marked_content()

    draw_line._bookloom_actual_text = True
    drawing.draw_text = draw_line
