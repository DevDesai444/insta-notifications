"""Finding, cleaning, and classifying URLs in captions and in image text.

Two hard cases drive the design:

1. Story link stickers arrive wrapped in Instagram's redirector
   (``l.instagram.com/?u=<percent-encoded real url>``). Unwrapping it gives
   the actual Workday link, which is what we want to open in Safari.
2. Links that were never clickable in the first place — a screenshot of a
   Workday posting — reach us as text read out of the image, complete with
   line breaks and stray spaces. Those need stitching back together.
"""

from __future__ import annotations

import re
from urllib.parse import parse_qs, unquote, urlparse

# Applicant tracking systems and job boards worth flagging in the title.
JOB_HOSTS = {
    "myworkdayjobs.com": "Workday",
    "myworkdaysite.com": "Workday",
    "wd1.myworkdayjobs.com": "Workday",
    "greenhouse.io": "Greenhouse",
    "boards.greenhouse.io": "Greenhouse",
    "job-boards.greenhouse.io": "Greenhouse",
    "lever.co": "Lever",
    "jobs.lever.co": "Lever",
    "ashbyhq.com": "Ashby",
    "jobs.ashbyhq.com": "Ashby",
    "icims.com": "iCIMS",
    "taleo.net": "Taleo",
    "smartrecruiters.com": "SmartRecruiters",
    "jobvite.com": "Jobvite",
    "workable.com": "Workable",
    "successfactors.com": "SuccessFactors",
    "eightfold.ai": "Eightfold",
    "avature.net": "Avature",
    "brassring.com": "BrassRing",
    "oraclecloud.com": "Oracle",
    "linkedin.com": "LinkedIn",
    "indeed.com": "Indeed",
    "simplify.jobs": "Simplify",
    "ripplematch.com": "RippleMatch",
    "handshake.com": "Handshake",
    "joinhandshake.com": "Handshake",
}

# Deliberately conservative: a bare-domain match needs one of these endings,
# otherwise "e.g" and "vs.io" in ordinary prose become fake links.
_BARE_TLDS = (
    "com|org|net|io|co|ai|dev|app|jobs|careers|edu|gov|us|uk|ca|in|me|xyz|"
    "tech|work|inc|life|so|sh|ly|gg|to|fyi|cloud|site|team|hr"
)

_SCHEME_RE = re.compile(r"https?://[^\s<>\"'`\]\)\},]+", re.IGNORECASE)
_BARE_RE = re.compile(
    r"(?<![@\w./-])"                              # not mid-URL, not an email
    r"((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"  # one or more labels
    rf"(?:{_BARE_TLDS}))"                          # a plausible TLD
    r"(/[^\s<>\"'`\]\)\},]*)?",                    # optional path
    re.IGNORECASE,
)

# Trailing characters that are almost always sentence punctuation, not URL.
_TRAILING_JUNK = ".,;:!?'\"`)]}>*_-–—…"

# Instagram redirect wrappers we should unwrap to reveal the real destination.
_REDIRECT_HOSTS = {"l.instagram.com", "l.facebook.com", "lm.facebook.com", "out.reddit.com"}


def unwrap_redirect(url: str) -> str:
    """Turn ``l.instagram.com/?u=https%3A%2F%2Fx.com%2Fy`` into ``https://x.com/y``."""
    for _ in range(3):  # redirectors occasionally nest
        try:
            parsed = urlparse(url)
        except ValueError:
            return url
        if parsed.netloc.lower() not in _REDIRECT_HOSTS:
            return url
        params = parse_qs(parsed.query)
        target = (params.get("u") or params.get("url") or [""])[0]
        if not target:
            return url
        url = unquote(target)
    return url


def clean_url(raw: str) -> str:
    """Normalize one candidate URL, or return '' if it isn't usable."""
    if not raw:
        return ""
    url = raw.strip().strip("​﻿")

    # Vision/OCR output often breaks a long URL across lines.
    url = re.sub(r"\s+", "", url)

    url = url.rstrip(_TRAILING_JUNK)
    # Keep balanced parens that are genuinely part of the path.
    while url.endswith(")") and url.count("(") < url.count(")"):
        url = url[:-1]

    if not url:
        return ""

    if not re.match(r"^https?://", url, re.IGNORECASE):
        if url.lower().startswith("www.") or re.match(r"^[\w-]+(\.[\w-]+)+", url):
            url = "https://" + url
        else:
            return ""

    url = unwrap_redirect(url)

    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    if not parsed.netloc or "." not in parsed.netloc:
        return ""
    # A host label must not be empty (catches "https://foo..com").
    if any(part == "" for part in parsed.netloc.split(".")):
        return ""
    return url


def extract_urls(text: str) -> list[str]:
    """All usable URLs in ``text``, normalized, de-duplicated, in order."""
    if not text:
        return []

    found: list[str] = []
    spans: list[tuple[int, int]] = []

    for match in _SCHEME_RE.finditer(text):
        found.append(match.group(0))
        spans.append(match.span())

    for match in _BARE_RE.finditer(text):
        start, end = match.span()
        # Skip anything already covered by a scheme match.
        if any(s <= start < e for s, e in spans):
            continue
        found.append(match.group(0))

    seen: set[str] = set()
    result: list[str] = []
    for candidate in found:
        url = clean_url(candidate)
        if not url:
            continue
        key = url.rstrip("/").lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(url)
    return result


def stitch_broken_urls(text: str) -> str:
    """Rejoin URLs that image text split across lines or on a space.

    Vision models transcribing a screenshot regularly emit
    ``https://acme.wd5.myworkdayjobs.com/en-US/\\nExternal/job/...``.
    """
    if not text:
        return ""
    # Join a line ending mid-URL with the next line.
    text = re.sub(r"(https?://[^\s]*)\n\s*(?=[^\s\n])", r"\1", text, flags=re.IGNORECASE)
    # Remove a single space that splits a scheme from its host.
    text = re.sub(r"(https?://)\s+", r"\1", text, flags=re.IGNORECASE)
    # Remove spaces around dots and slashes inside an obvious URL run.
    text = re.sub(
        r"(https?://[\w.-]*)\s*([./])\s*(?=[\w-])", r"\1\2", text, flags=re.IGNORECASE
    )
    return text


def job_platform(url: str) -> str:
    """'Workday', 'Greenhouse', ... or '' if the host isn't a known ATS."""
    try:
        host = urlparse(url).netloc.lower()
    except ValueError:
        return ""
    host = host.split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    for suffix, name in JOB_HOSTS.items():
        if host == suffix or host.endswith("." + suffix):
            return name
    return ""


def is_job_link(url: str) -> bool:
    return bool(job_platform(url))


def guess_company(url: str) -> str:
    """Best-effort company name from an ATS URL.

    ``https://nvidia.wd5.myworkdayjobs.com/...``   -> 'Nvidia'
    ``https://boards.greenhouse.io/stripe/jobs/1`` -> 'Stripe'
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return ""
    host = parsed.netloc.lower().split(":")[0]
    if host.startswith("www."):
        host = host[4:]
    parts = host.split(".")
    platform = job_platform(url)

    if platform == "Workday" and len(parts) >= 3:
        # <tenant>.wd<N>.myworkdayjobs.com
        return parts[0].replace("-", " ").title()
    if platform in {"Greenhouse", "Lever", "Ashby"}:
        segments = [s for s in parsed.path.split("/") if s]
        if segments:
            return segments[0].replace("-", " ").title()
    if platform in {"SmartRecruiters", "Workable", "iCIMS"} and len(parts) >= 3:
        return parts[0].replace("-", " ").title()
    if not platform and len(parts) >= 2:
        return parts[-2].replace("-", " ").title()
    return ""


def rank_links(urls: list[str]) -> list[str]:
    """Put the link the user most likely wants to tap first: real ATS links."""
    return sorted(urls, key=lambda u: (not is_job_link(u), len(u)))
