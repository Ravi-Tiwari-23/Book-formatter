from __future__ import annotations

import hashlib
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

class ImageFirewallError(RuntimeError):
    pass


def image_fingerprint(data: bytes) -> str:
    with Image.open(BytesIO(data)) as image:
        normalized = image.convert("RGBA")
        payload = f"{normalized.width}x{normalized.height}:".encode() + normalized.tobytes()
    return hashlib.sha256(payload).hexdigest()


def pdf_image_fingerprints(path: str | Path) -> set[str]:
    result: set[str] = set()
    with pymupdf.open(path) as document:
        for page in document:
            for image in page.get_images(full=True):
                result.add(image_fingerprint(document.extract_image(image[0])["image"]))
    return result


def verify_image_firewall(
    *,
    output_fingerprints: set[str],
    source_fingerprints: set[str],
    reference_fingerprints: set[str],
    approved_local_fingerprints: set[str] | None = None,
) -> dict[str, int]:
    approved = source_fingerprints | (approved_local_fingerprints or set())
    reference_only = (output_fingerprints & reference_fingerprints) - approved
    unknown = output_fingerprints - approved
    if reference_only:
        raise ImageFirewallError(
            f"Reference image firewall failed: {len(reference_only)} reference-only image(s) in output"
        )
    if unknown:
        raise ImageFirewallError(
            f"Image provenance failed: {len(unknown)} output image(s) are not approved source assets"
        )
    return {
        "output_images": len(output_fingerprints),
        "source_images": len(output_fingerprints & source_fingerprints),
        "approved_local_images": len(output_fingerprints & (approved_local_fingerprints or set())),
        "reference_images_included": 0,
    }

