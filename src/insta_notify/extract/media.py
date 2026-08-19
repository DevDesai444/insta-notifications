"""Downloading and preparing Instagram media for analysis and attachment."""

from __future__ import annotations

import hashlib
import io
import logging
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_UA = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)

MAX_EDGE = 1280          # plenty to read a URL off a screenshot
JPEG_QUALITY = 88


def download(url: str, dest_dir: Path, timeout: int = 20) -> Path | None:
    """Fetch a media URL to ``dest_dir``. Returns the path, or None on failure."""
    if not url:
        return None
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ".jpg"
    path = dest_dir / name
    if path.exists() and path.stat().st_size > 0:
        return path
    try:
        resp = requests.get(url, timeout=timeout, headers={"User-Agent": _UA})
        resp.raise_for_status()
        path.write_bytes(resp.content)
        return path
    except Exception as exc:  # network/HTTP problems must not kill the poll loop
        log.warning("could not download media %s: %s", url[:80], exc)
        return None


def prepare_for_vision(path: Path) -> tuple[bytes, str] | None:
    """Downscale and re-encode so the vision call stays small and fast.

    Returns ``(bytes, media_type)`` or None if the file isn't a readable image.
    """
    try:
        from PIL import Image
    except ImportError:  # Pillow missing -> send the original bytes
        try:
            return path.read_bytes(), "image/jpeg"
        except OSError:
            return None

    try:
        with Image.open(path) as img:
            img = img.convert("RGB")
            if max(img.size) > MAX_EDGE:
                ratio = MAX_EDGE / max(img.size)
                new_size = (max(1, int(img.width * ratio)), max(1, int(img.height * ratio)))
                img = img.resize(new_size, Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=JPEG_QUALITY)
            return buf.getvalue(), "image/jpeg"
    except Exception as exc:
        log.warning("could not prepare image %s: %s", path, exc)
        return None


def cleanup(dest_dir: Path, keep: int = 60) -> None:
    """Keep the media cache from growing without bound."""
    try:
        files = sorted(
            (p for p in dest_dir.glob("*.jpg") if p.is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for stale in files[keep:]:
            stale.unlink(missing_ok=True)
    except OSError:
        pass
