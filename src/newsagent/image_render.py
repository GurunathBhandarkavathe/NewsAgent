from __future__ import annotations

import io
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

from .briefs import slide_brief
from .config import Config
from .models import Draft, DraftStory
from .utils import source_from_url


CANVAS = (1080, 1350)
IMAGE_BOX = (0, 0, 1080, 890)
PANEL_BOX = (0, 890, 1080, 1350)
CATEGORY_COLORS = {
    "politics": (213, 62, 79),
    "films": (131, 83, 181),
    "sports": (42, 157, 143),
    "current_affairs": (244, 162, 97),
    "international": (69, 123, 157),
}


def render_draft_images(draft: Draft, config: Config) -> None:
    draft_dir = config.assets_dir / "drafts" / draft.id
    draft_dir.mkdir(parents=True, exist_ok=True)
    total = len(draft.stories)
    for index, story in enumerate(draft.stories, start=1):
        output = draft_dir / f"slide-{index:02d}.jpg"
        render_slide(story, output, index, total, config)
        story.slide_path = str(output)


def render_slide(story: DraftStory, output_path: Path, index: int, total: int, config: Config) -> None:
    image = Image.new("RGB", CANVAS, (246, 247, 241))
    draw = ImageDraw.Draw(image)
    category_color = CATEGORY_COLORS.get(story.category, (40, 40, 40))

    article_image = load_remote_image(story.image_url) if config.uses_article_images else None
    if article_image:
        fitted = ImageOps.fit(article_image.convert("RGB"), (1080, 890), method=Image.Resampling.LANCZOS)
        image.paste(fitted, IMAGE_BOX[:2])
        overlay = Image.new("RGBA", (1080, 890), (0, 0, 0, 65))
        image.paste(Image.alpha_composite(image.crop(IMAGE_BOX).convert("RGBA"), overlay).convert("RGB"), IMAGE_BOX[:2])
        story.rights_risk = "reused_article_image_requires_manual_rights_review"
    else:
        draw_fallback_visual(image, story, category_color, config.brand_name)
        story.rights_risk = (
            "fallback_visual_no_article_image"
            if config.uses_article_images
            else "branded_card_no_external_news_image"
        )

    brief_font = load_font(42, bold=True)
    meta_font = load_font(30, bold=True)
    small_font = load_font(24)
    source_font = load_font(26)

    draw.rounded_rectangle((42, 42, 252, 100), radius=18, fill=category_color)
    draw.text((66, 56), f"{index}/{total}", font=meta_font, fill=(255, 255, 255))
    brand_label = config.brand_name.upper()[:18]
    brand_bbox = draw.textbbox((0, 0), brand_label, font=meta_font)
    brand_width = min(370, brand_bbox[2] - brand_bbox[0] + 52)
    draw.rounded_rectangle((1080 - brand_width - 42, 42, 1038, 100), radius=18, fill=(250, 249, 244))
    draw.text((1080 - brand_width - 16, 56), brand_label, font=meta_font, fill=(24, 28, 32))

    draw.rectangle(PANEL_BOX, fill=(250, 249, 244))
    draw.rectangle((0, 890, 1080, 902), fill=category_color)

    category = story.category.replace("_", " ").upper()
    draw.text((64, 936), category, font=meta_font, fill=category_color)

    brief = slide_brief(story)
    wrapped = wrap_text(brief, brief_font, 930, max_lines=4)
    draw.multiline_text((64, 992), wrapped, font=brief_font, fill=(24, 28, 32), spacing=10)

    courtesy = f"Courtesy: {story.source}"
    host = source_from_url(story.url)
    draw.text((64, 1260), courtesy[:78], font=source_font, fill=(52, 58, 64))
    draw.text((64, 1295), host[:78], font=small_font, fill=(92, 96, 100))

    output_path.parent.mkdir(parents=True, exist_ok=True)
    image.save(output_path, "JPEG", quality=92, optimize=True)


def draw_fallback_visual(image: Image.Image, story: DraftStory, category_color: tuple[int, int, int], brand_name: str) -> None:
    accent = mix(category_color, (255, 255, 255), 0.42)
    deep = mix(category_color, (24, 30, 34), 0.28)
    warm = mix(category_color, (255, 229, 180), 0.62)

    background = Image.new("RGB", (1080, 890), (255, 255, 255))
    bg_draw = ImageDraw.Draw(background)
    for y in range(890):
        t = y / 889
        color = mix(mix(accent, (248, 250, 244), 0.72), warm, t * 0.52)
        bg_draw.line((0, y, 1080, y), fill=color)

    overlay = Image.new("RGBA", (1080, 890), (0, 0, 0, 0))
    od = ImageDraw.Draw(overlay)
    od.polygon([(-180, 90), (420, -120), (1240, 460), (1240, 690), (-180, 315)], fill=(*category_color, 210))
    od.polygon([(610, -80), (1210, -40), (1210, 890), (925, 890), (755, 250)], fill=(*deep, 160))
    od.polygon([(-120, 650), (440, 450), (1160, 760), (1160, 950), (-120, 930)], fill=(*warm, 190))
    for x in range(72, 1030, 104):
        for y in range(92, 810, 104):
            od.ellipse((x, y, x + 10, y + 10), fill=(255, 255, 255, 78))
    background = Image.alpha_composite(background.convert("RGBA"), overlay).convert("RGB")
    image.paste(background, IMAGE_BOX[:2])

    draw = ImageDraw.Draw(image)
    label_font = load_font(44, bold=True)
    large_font = load_font(108, bold=True)
    small_font = load_font(30, bold=True)
    category = story.category.replace("_", " ").upper()

    draw.rounded_rectangle((68, 640, 1012, 805), radius=28, fill=(255, 255, 255))
    draw.text((96, 666), brand_name.upper()[:28], font=small_font, fill=(48, 54, 58))
    draw.text((96, 710), category, font=label_font, fill=category_color)
    draw.text((80, 210), "NEWS", font=large_font, fill=(255, 255, 255))
    draw.text((86, 318), "UPDATE", font=large_font, fill=(255, 255, 255))


def mix(first: tuple[int, int, int], second: tuple[int, int, int], amount: float) -> tuple[int, int, int]:
    return tuple(int(first[i] * (1 - amount) + second[i] * amount) for i in range(3))


def load_remote_image(url: str) -> Image.Image | None:
    if not url:
        return None
    if is_blocked_image_url(url):
        return None
    try:
        response = requests.get(url, timeout=12, headers={"User-Agent": "NewsAgent/0.1"})
        response.raise_for_status()
        if "image" not in response.headers.get("content-type", "") and not url.lower().endswith(
            (".jpg", ".jpeg", ".png", ".webp")
        ):
            return None
        image = Image.open(io.BytesIO(response.content))
        if not is_usable_article_image(image):
            return None
        return image
    except Exception:
        return None


def is_blocked_image_url(url: str) -> bool:
    lowered = url.lower()
    blocked = (
        "logo",
        "sprite",
        "favicon",
        "icon-",
        "/icon",
        "avatar",
        "author",
        "placeholder",
        "default-image",
        "default_img",
        "blank.",
        "transparent.",
        "tracking",
    )
    return any(token in lowered for token in blocked)


def is_usable_article_image(image: Image.Image) -> bool:
    width, height = image.size
    if width < 420 or height < 260:
        return False
    ratio = width / height if height else 0
    if ratio < 0.45 or ratio > 3.2:
        return False
    return True


def load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial Bold.ttf" if bold else "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size=size)
    return ImageFont.load_default()


def wrap_text(text: str, font: ImageFont.ImageFont, width: int, max_lines: int = 3) -> str:
    words = text.split()
    lines: list[str] = []
    current = ""
    probe = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(probe)
    for word in words:
        candidate = f"{current} {word}".strip()
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] <= width or not current:
            current = candidate
        else:
            lines.append(current)
            current = word
    if current:
        lines.append(current)
    if len(lines) <= max_lines:
        return "\n".join(lines)
    clipped = lines[:max_lines]
    clipped[-1] = fit_with_ellipsis(clipped[-1], font, width)
    return "\n".join(clipped)


def fit_with_ellipsis(text: str, font: ImageFont.ImageFont, width: int) -> str:
    probe = Image.new("RGB", (10, 10))
    draw = ImageDraw.Draw(probe)
    words = text.rstrip(" .,…").split()
    while words:
        candidate = " ".join(words) + "..."
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if bbox[2] <= width:
            return candidate
        words.pop()
    return "..."
