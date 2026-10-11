from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .models import ProcessingJob, ProcessingOptions


def create_job(
    source_upload_name: str,
    source_path: Path,
    reference_upload_name: str,
    reference_path: Path,
    options: ProcessingOptions,
) -> ProcessingJob:
    """Create an independent processing job for a pair of uploaded PDFs."""

    return ProcessingJob(
        id=uuid4().hex,
        source_upload_name=source_upload_name,
        source_path=Path(source_path),
        reference_upload_name=reference_upload_name,
        reference_path=Path(reference_path),
        options=options,
    )
