from __future__ import annotations

import re

from .briefs import complete_sentence, story_context
from .models import DraftStory
from .utils import source_from_url, truncate_words


INSTAGRAM_CAPTION_MAX_CHARS = 2200
PUBLISH_CAPTION_MAX_CHARS = 2100

OPENERS = (
    "{brand} trend watch: the top India updates this cycle.",
    "Top India-linked stories from {brand} right now.",
    "Here are the key updates shaping the news cycle.",
    "A quick {brand} briefing on major India-linked updates.",
)

HASHTAG_SETS = (
    "{brand_tag} #BharatNews #TrendingNews #NewsUpdate",
    "{brand_tag} #IndiaUpdates #BreakingNews #DailyNews",
    "{brand_tag} #TopStories #WorldNews #SportsNews",
    "{brand_tag} #NewsBrief #BharatUpdate #InstaNews",
)


def build_caption(
    stories: list[DraftStory],
    variant: int = 0,
    *,
    brand_name: str = "Samachar Bharat",
    brand_handle: str = "@samachar.bharat_",
    brand_tagline: str = "clear Bharat updates every 3 hours.",
    max_chars: int = PUBLISH_CAPTION_MAX_CHARS,
) -> str:
    variant_index = variant % len(OPENERS)
    for detail_chars in (210, 170, 140, 110):
        caption = compose_caption(
            stories,
            variant_index,
            brand_name=brand_name,
            brand_handle=brand_handle,
            brand_tagline=brand_tagline,
            detail_max_chars=detail_chars,
            include_full_urls=True,
        )
        if len(caption) <= max_chars:
            return caption

    compact = compose_caption(
        stories,
        variant_index,
        brand_name=brand_name,
        brand_handle=brand_handle,
        brand_tagline=brand_tagline,
        detail_max_chars=110,
        include_full_urls=False,
    )
    return fit_caption_to_instagram(compact, max_chars=max_chars)


def build_story_post_caption(
    story: DraftStory,
    index: int,
    total: int,
    *,
    brand_name: str = "Samachar Bharat",
    brand_handle: str = "@samachar.bharat_",
    brand_tagline: str = "clear Bharat updates every 3 hours.",
    max_chars: int = PUBLISH_CAPTION_MAX_CHARS,
) -> str:
    label = story.category.replace("_", " ").title()
    title = truncate_words(story.title, max_words=24, max_chars=180)
    detail = complete_sentence(story_context(story, max_words=210, max_chars=1450))
    source = truncate_words(story.source.rstrip("."), max_words=10, max_chars=90)
    host = source_from_url(story.url)
    lines = [
        f"{brand_name} update {index}/{total}: {label}",
        "",
        "What happened:",
        f"- {title}",
        "",
        "Full details:",
        *[f"- {point}" for point in detail_points(detail)],
        "",
        "Source and reference:",
        f"- Courtesy: {source or host}",
        f"- Full report: {story.url}",
        "",
        f"Follow {brand_handle} for {brand_tagline}",
        f"{brand_hashtag(brand_name)} #BharatNews #NewsUpdate",
    ]
    return fit_caption_to_instagram("\n".join(lines), max_chars=max_chars)


def compose_caption(
    stories: list[DraftStory],
    variant_index: int,
    *,
    brand_name: str,
    brand_handle: str,
    brand_tagline: str,
    detail_max_chars: int,
    include_full_urls: bool,
) -> str:
    lines: list[str] = [OPENERS[variant_index].format(brand=brand_name)]
    for index, story in enumerate(stories, start=1):
        lines.extend(story_lines(index, story, variant_index, detail_max_chars, include_full_urls))

    lines.append("Read full reports from the links listed with each update above.")
    lines.append(f"Follow {brand_handle} for {brand_tagline}")
    lines.append(HASHTAG_SETS[variant_index].format(brand_tag=brand_hashtag(brand_name)))
    return "\n".join(lines)


def story_lines(
    index: int,
    story: DraftStory,
    variant_index: int,
    detail_max_chars: int = 170,
    include_full_urls: bool = True,
) -> list[str]:
    label = story.category.replace("_", " ").title()
    title = truncate_words(story.title, max_words=14, max_chars=96)
    detail = complete_sentence(story_context(story, max_words=30, max_chars=detail_max_chars))
    source = truncate_words(story.source.rstrip("."), max_words=6, max_chars=56)
    host = source_from_url(story.url)

    if variant_index == 1:
        first = f"{index}. {title} ({label})"
        detail_prefix = "Details"
    elif variant_index == 2:
        first = f"{index}. {label} update - {title}"
        detail_prefix = "Context"
    else:
        first = f"{index}. {label}: {title}"
        detail_prefix = "Details"
    return [
        first,
        f"- {detail_prefix}: {detail}",
    ]


def source_line(source: str, host: str, url: str, include_full_url: bool) -> str:
    return ""


def fit_caption_to_instagram(caption: str, max_chars: int = PUBLISH_CAPTION_MAX_CHARS) -> str:
    if len(caption) <= max_chars:
        return caption
    suffix = "\n#SamacharBharat #NewsBrief"
    room = max(0, max_chars - len(suffix))
    trimmed = caption[:room].rsplit("\n", 1)[0].rstrip()
    if not trimmed:
        trimmed = caption[:room].rstrip()
    return f"{trimmed}{suffix}"[:max_chars]


def brand_hashtag(brand_name: str) -> str:
    tag = "".join(part for part in brand_name.title() if part.isalnum())
    return f"#{tag or 'SamacharBharat'}"


def detail_points(text: str, max_points: int = 6) -> list[str]:
    detail = complete_sentence(text)
    if not detail:
        return []
    points = [point.strip() for point in re.split(r"(?<=[.!?])\s+", detail) if point.strip()]
    if len(points) <= max_points:
        return points
    return [*points[: max_points - 1], " ".join(points[max_points - 1 :])]
