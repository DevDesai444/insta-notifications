"""Read job links and context straight out of an Instagram image.

This is the piece that solves "he posts Workday links that aren't clickable in
stories". A screenshot of a job posting has the URL rendered as pixels; the
only way to get a tappable link out of it is to read the image. Claude does
that far more reliably than classic OCR on the character classes that matter
here (l/1/I, 0/O, rn/m) — and it can also tell us whether the post is even
about a new grad role.

Everything degrades gracefully: if there is no API key, the SDK is missing, or
the call fails, the caller falls back to plain regex over the caption.
"""

from __future__ import annotations

import base64
import logging
from typing import Optional

from ..models import Extraction
from .urls import clean_url, extract_urls, rank_links, stitch_broken_urls

log = logging.getLogger(__name__)

_SYSTEM = """\
You read screenshots and photos posted by an Instagram account that shares new \
grad / early-career software job openings.

Your job is to extract, with total precision:
1. Every URL visible anywhere in the image, INCLUDING links that are only \
rendered as text (screenshots of a browser address bar, a Workday posting, a \
chat message, a slide). Transcribe each URL character by character exactly as \
shown. Do not guess, expand, shorten, or "correct" a URL. Do not invent a \
scheme that isn't there. If a URL is cut off or unreadable, include the part \
you can actually see and nothing more.
2. A short, plain description of what the image says, so someone who cannot see \
it still knows whether to care.

Be careful with characters that look alike: l vs 1 vs I, 0 vs O, rn vs m, - vs _.

Set is_job_related true if the image is about a job/internship/new grad role, \
hiring, applications, referrals, or career advice for landing such a role. Set \
it false only for clearly unrelated content.
"""


def _build_schema_model():
    """Defined lazily so the package imports fine without pydantic/anthropic."""
    from pydantic import BaseModel, Field

    class ImageAnalysis(BaseModel):
        is_job_related: bool = Field(
            description="True if this is about a job, internship, or hiring."
        )
        summary: str = Field(
            description="One or two sentences describing what the image says."
        )
        urls: list[str] = Field(
            default_factory=list,
            description="Every URL visible in the image, transcribed exactly.",
        )
        company: str = Field(
            default="", description="Company name if clearly identifiable, else ''."
        )
        role: str = Field(
            default="", description="Role title if clearly identifiable, else ''."
        )
        visible_text: str = Field(
            default="", description="The meaningful text content of the image."
        )

    return ImageAnalysis


class VisionExtractor:
    """Wraps one small Claude vision call per image."""

    def __init__(self, api_key: str, model: str = "claude-opus-5"):
        self.model = model
        self._client = None
        self._analysis_model = None
        self._disabled = False
        if not api_key:
            self._disabled = True
            return
        try:
            import anthropic

            self._client = anthropic.Anthropic(api_key=api_key, timeout=45.0, max_retries=1)
            self._analysis_model = _build_schema_model()
        except Exception as exc:
            log.warning("vision disabled (%s); falling back to caption-only links", exc)
            self._disabled = True

    @property
    def available(self) -> bool:
        return not self._disabled and self._client is not None

    def analyze(
        self, image_bytes: bytes, media_type: str = "image/jpeg", caption: str = ""
    ) -> Optional[Extraction]:
        """Return an Extraction, or None if the call could not be made."""
        if not self.available or not image_bytes:
            return None

        prompt = (
            "Extract all visible URLs and describe this image."
            if not caption
            else (
                "Extract all visible URLs and describe this image.\n\n"
                f"The post's caption, for context:\n{caption[:1500]}"
            )
        )
        content = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": base64.standard_b64encode(image_bytes).decode("utf-8"),
                },
            },
            {"type": "text", "text": prompt},
        ]

        try:
            response = self._client.messages.parse(
                model=self.model,
                max_tokens=2000,
                system=_SYSTEM,
                # Low effort: this is transcription, and a fast answer matters
                # more than deep reasoning when the user wants a live alert.
                output_config={"effort": "low"},
                messages=[{"role": "user", "content": content}],
                output_format=self._analysis_model,
            )
        except TypeError:
            # Older SDK without output_config support on parse().
            try:
                response = self._client.messages.parse(
                    model=self.model,
                    max_tokens=2000,
                    system=_SYSTEM,
                    messages=[{"role": "user", "content": content}],
                    output_format=self._analysis_model,
                )
            except Exception as exc:
                log.warning("vision call failed: %s", exc)
                return None
        except Exception as exc:
            log.warning("vision call failed: %s", exc)
            return None

        if getattr(response, "stop_reason", None) == "refusal":
            log.info("vision call refused; using caption links only")
            return None

        parsed = getattr(response, "parsed_output", None)
        if parsed is None:
            return None

        return self._to_extraction(parsed)

    @staticmethod
    def _to_extraction(parsed) -> Extraction:
        links: list[str] = []
        for raw in getattr(parsed, "urls", []) or []:
            cleaned = clean_url(str(raw))
            if cleaned:
                links.append(cleaned)

        visible_text = getattr(parsed, "visible_text", "") or ""
        # The model sometimes describes a URL in prose instead of listing it.
        for found in extract_urls(stitch_broken_urls(visible_text)):
            if found not in links:
                links.append(found)

        seen: set[str] = set()
        deduped: list[str] = []
        for url in links:
            key = url.rstrip("/").lower()
            if key not in seen:
                seen.add(key)
                deduped.append(url)

        return Extraction(
            links=rank_links(deduped),
            summary=(getattr(parsed, "summary", "") or "").strip(),
            image_text=visible_text.strip(),
            is_job_related=bool(getattr(parsed, "is_job_related", True)),
            company=(getattr(parsed, "company", "") or "").strip(),
            role=(getattr(parsed, "role", "") or "").strip(),
            source="vision",
        )
