from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from html import unescape
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse


TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
}


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def isoformat(dt: datetime | None) -> str | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def parse_datetime(value: object) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if hasattr(value, "tm_year"):
        return datetime(*value[:6], tzinfo=timezone.utc)
    text = str(value).strip()
    if not text:
        return None
    try:
        return parsedate_to_datetime(text).astimezone(timezone.utc)
    except Exception:
        pass
    for fmt in ("%Y%m%d%H%M%S", "%Y%m%d%H%M", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def clean_text(value: object) -> str:
    text = unescape(str(value or ""))
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def canonicalize_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url.strip())
    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if k.lower() not in TRACKING_PARAMS]
    netloc = parsed.netloc.lower()
    path = parsed.path.rstrip("/") or parsed.path
    return urlunparse((parsed.scheme.lower() or "https", netloc, path, "", urlencode(query), ""))


def source_from_url(url: str) -> str:
    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    return host or "unknown source"


def normalize_title(title: str) -> str:
    text = clean_text(title).lower()
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    text = re.sub(r"\b(the|a|an|and|or|of|to|in|on|for|with|as|by|from|at|is|are)\b", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def story_key(title: str, url: str = "") -> str:
    canonical = canonicalize_url(url)
    normalized = normalize_title(title)
    base = canonical or normalized
    return hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def cluster_key(title: str) -> str:
    words = normalize_title(title).split()
    return " ".join(words[:12])


def truncate_words(text: str, max_words: int = 16, max_chars: int = 130) -> str:
    words = clean_text(text).split()
    clipped = " ".join(words[:max_words])
    if len(clipped) > max_chars:
        clipped = clipped[: max_chars - 1].rsplit(" ", 1)[0]
    if len(words) > max_words or len(clean_text(text)) > len(clipped):
        return clipped.rstrip(" .,") + "..."
    return clipped


def slugify(text: str, fallback: str = "item") -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", clean_text(text).lower()).strip("-")
    return slug[:80] or fallback


def ensure_relative_to(path: Path, root: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
