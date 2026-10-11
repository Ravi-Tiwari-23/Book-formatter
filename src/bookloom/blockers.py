from __future__ import annotations

from .models import BookSection, Correction, ReviewStatus


class BuildBlockedError(RuntimeError):
    def __init__(self, reasons: list[str]):
        self.reasons = reasons
        super().__init__("Production build blocked: " + "; ".join(reasons))


def validate_production_readiness(
    *,
    sections: list[BookSection],
    corrections: list[Correction],
    expected_section_numbers: set[int],
    protected_assets_present: bool,
    reference_images_included: int,
    fonts_ok: bool,
) -> None:
    reasons: list[str] = []
    actual = {section.number for section in sections if section.number is not None}
    missing = sorted(expected_section_numbers - actual)
    if missing:
        reasons.append(f"missing remedy sections: {missing}")
    if any(item.status == ReviewStatus.PENDING for item in corrections):
        reasons.append("unresolved review items remain")
    if not protected_assets_present:
        reasons.append("protected TRUELOGER assets are not confirmed")
    if reference_images_included:
        reasons.append(f"reference images entered output: {reference_images_included}")
    if not fonts_ok:
        reasons.append("font verification failed")
    if reasons:
        raise BuildBlockedError(reasons)

