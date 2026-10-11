from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import streamlit as st


@dataclass(slots=True)
class UploadRequest:
    source: Any | None
    reference: Any | None
    tesseract_path: str
    preserve_original_cover: bool
    submitted: bool


def render_brand_header(stage: str) -> None:
    st.title("Bookloom")
    st.caption("Source-faithful PDF review and professional book production")
    labels = {
        "upload": "1 Upload",
        "review": "2 Review",
        "build": "3 Build",
        "download": "4 Download",
    }
    active = list(labels).index(stage) if stage in labels else 0
    columns = st.columns(4)
    for index, (key, label) in enumerate(labels.items()):
        marker = "●" if index == active else "✓" if index < active else "○"
        columns[index].caption(f"{marker} {label}")


def render_upload_panel() -> UploadRequest:
    with st.container(border=True):
        st.subheader("Start a book")
        st.write(
            "Upload the source you want to publish and a reference PDF used only to validate wording."
        )
        with st.form("bookloom-upload-form", clear_on_submit=False):
            left, right = st.columns(2)
            with left:
                source = st.file_uploader(
                    "Source PDF",
                    type="pdf",
                    key="source",
                    help="The source controls content, images, title, author, and metadata.",
                )
            with right:
                reference = st.file_uploader(
                    "Reference PDF",
                    type="pdf",
                    key="reference",
                    help="Used for wording validation only; its images and layout are never copied.",
                )
            with st.expander("Processing options"):
                tesseract_path = st.text_input(
                    "Optional Tesseract executable path",
                    key="tesseract_path",
                    placeholder=r"C:\Program Files\Tesseract-OCR\tesseract.exe",
                )
                preserve = st.checkbox(
                    "Use detected source cover instead of the generated Reading Edition cover",
                    value=False,
                    key="preserve-original-cover",
                )
            submitted = st.form_submit_button(
                "Analyze PDFs",
                type="primary",
                disabled=not (source and reference),
                width="stretch",
            )
    return UploadRequest(source, reference, tesseract_path, preserve, submitted)


def friendly_build_error(error: Exception) -> str:
    message = str(error)
    if "GTK/Pango" in message or "WeasyPrint" in message:
        return "Final PDF rendering is unavailable. Configure the bundled GTK/Pango runtime, then retry."
    if "manual edit" in message.casefold():
        return "One manual edit is empty. Add the intended wording or return that finding to its safe default."
    return message or "Bookloom could not complete this build. Review the diagnostics and try again."
