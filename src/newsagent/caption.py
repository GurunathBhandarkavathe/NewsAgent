from __future__ import annotations

from .briefs import description_detail
from .models import DraftStory
from .utils import source_from_url, truncate_words


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
    brand_handle: str = "@smachar.bh",
    brand_tagline: str = "Bharat in 5 slides. Every 3 hours.",
) -> str:
    variant_index = variant % len(OPENERS)
    lines: list[str] = [OPENERS[variant_index].format(brand=brand_name)]
    for index, story in enumerate(stories, start=1):
        lines.extend(story_lines(index, story, variant_index))

    source_names = ", ".join(dict.fromkeys(story.source for story in stories))
    lines.append(f"Sources/courtesy: {source_names}.")
    lines.append("Read full reports from the links listed with each update above.")
    lines.append(f"Follow {brand_handle} for {brand_tagline}")
    lines.append(HASHTAG_SETS[variant_index].format(brand_tag=brand_hashtag(brand_name)))
    return "\n".join(lines)


def story_lines(index: int, story: DraftStory, variant_index: int) -> list[str]:
    label = story.category.replace("_", " ").title()
    title = truncate_words(story.title, max_words=16, max_chars=130)
    detail = description_detail(story)
    source = story.source.rstrip(".")
    host = source_from_url(story.url)

    if variant_index == 1:
        first = f"{index}. {title} ({label})"
        detail_prefix = "Details"
    elif variant_index == 2:
        first = f"{index}. {label} update — {title}"
        detail_prefix = "Context"
    else:
        first = f"{index}. {label}: {title}"
        detail_prefix = "Details"
    return [
        first,
        f"{detail_prefix}: {detail}",
        f"Source/courtesy: {source} | Full report: {host}: {story.url}",
    ]


def brand_hashtag(brand_name: str) -> str:
    tag = "".join(part for part in brand_name.title() if part.isalnum())
    return f"#{tag or 'SamacharBharat'}"
