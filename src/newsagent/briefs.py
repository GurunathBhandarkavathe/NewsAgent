from __future__ import annotations

import re

from .models import DraftStory
from .utils import clean_text, truncate_words


def slide_brief(story: DraftStory) -> str:
    summary = clean_text(story.summary)
    title_sentence = title_to_sentence(story.title)
    if summary and len(summary) <= 150 and summary.lower() != clean_text(story.title).lower():
        return complete_sentence(truncate_words(summary, max_words=22, max_chars=150))
    return complete_sentence(truncate_words(title_sentence, max_words=22, max_chars=150))


def description_detail(story: DraftStory) -> str:
    return complete_sentence(story_context(story, max_words=58, max_chars=390))


def story_context(story: DraftStory, *, max_words: int, max_chars: int) -> str:
    summary = clean_text(story.summary)
    title = clean_text(story.title)
    if summary and summary.lower() != title.lower():
        return truncate_words(summary, max_words=max_words, max_chars=max_chars)

    trimmed_title = truncate_words(title, max_words=max_words, max_chars=max_chars - 20).rstrip(".")
    return trimmed_title


def complete_sentence(text: str) -> str:
    stripped = clean_text(text).rstrip()
    if not stripped:
        return ""
    if stripped.endswith((".", "!", "?")):
        return stripped
    if stripped.endswith("..."):
        return stripped
    return f"{stripped}."


def title_to_sentence(title: str) -> str:
    text = clean_text(title)
    text = re.sub(r"\s*\b[Ll]ive\s+[Uu]pdates?\b\s*[:|-]\s*", ": ", text)
    text = re.sub(r"\s*\b[Ww]atch\b\.?$", "", text).strip(" .")
    amid_match = re.match(r"(?i)^amid ([^,]+),\s*(.+)$", text)
    if amid_match:
        issue, update = amid_match.groups()
        text = f"{update} amid {issue}"
    if re.search(r"\b(says?|said|announces?|announced|orders?|ordered|asks?|asked|returns?|returned|visits?|visited|kills?|killed|wins?|won|drops?|dropped|convicts?|convicted|restrains?|restrained)\b", text, re.I):
        return text
    return text
