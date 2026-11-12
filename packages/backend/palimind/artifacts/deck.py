"""Presentation pipeline: outline → plan → render → validate.

The pipeline is intentionally split into small, testable stages:

``parse_outline``   turn the model's Markdown/slide list into raw specs
``plan_deck``       clean the content, infer a layout for each slide and split
                    over-long slides into continuation slides
``render_deck``     draw the deck with python-pptx (16:9, designed layouts)
``validate_deck``   reopen the bytes and check the result is a real, non-empty deck

Keeping planning separate from drawing is what lets an outline written by a
small local model still produce a designed deck: the renderer, not the model,
owns typography, spacing and layout choice.
"""

from __future__ import annotations

import io
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

# ── theme ──────────────────────────────────────────────────────────────────
W, H = 13.333, 7.5
INK = "0B1220"
INK_SOFT = "1E293B"
BODY = "334155"
MUTED = "64748B"
FAINT = "94A3B8"
LINE = "E2E8F0"
SURFACE = "F7F9FC"
CARD = "F1F5F9"
CARD_ALT = "EEF4FF"
WHITE = "FFFFFF"
ACCENT = "2563EB"
ACCENT_DEEP = "1D4ED8"
ACCENT_SOFT = "DBEAFE"
VIOLET = "7C3AED"
TEAL = "0D9488"
AMBER = "B45309"
ROSE = "BE123C"
DARK = "0A1224"
DARK_2 = "111D36"
DARK_LINE = "1E2A44"

FONT = "Aptos"
FONT_DISPLAY = "Aptos Display"

_MAX_BULLETS = 6
_MAX_BULLET_CHARS = 320


@dataclass(frozen=True)
class SlidePlan:
    """One slide after planning, before drawing."""

    title: str
    bullets: tuple[str, ...] = ()
    layout: str = "content"
    subtitle: str = ""
    hint: str = ""


@dataclass(frozen=True)
class DeckPlan:
    title: str
    subtitle: str = ""
    slides: tuple[SlidePlan, ...] = ()
    body: str = ""


# ── small text utilities ───────────────────────────────────────────────────
def _plain(value: str) -> str:
    """Strip inline Markdown that a slide shape cannot render."""
    text = str(value or "")
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(?<!\w)(\*|_)(.*?)\1(?!\w)", r"\2", text)
    text = text.replace("`", "").replace("~~", "")
    return re.sub(r"\s+", " ", text).strip()


def _clip(value: str, limit: int = _MAX_BULLET_CHARS) -> str:
    value = _plain(value)
    if len(value) <= limit:
        return value
    cut = value.rfind(" ", 0, limit)
    return value[: cut if cut > 40 else limit].rstrip(" ,.;:-–—") + "…"


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()


def _split_label(text: str) -> tuple[str, str]:
    """'Revenue: up 20%' → ('Revenue', 'up 20%'); otherwise one label."""
    raw = _plain(text)
    for separator in (":", " — ", " – ", " - "):
        if separator in raw:
            label, _, detail = raw.partition(separator)
            if 0 < len(label.strip()) <= 56:
                return label.strip(), detail.strip()
    return raw, ""


_METRIC_RE = re.compile(
    r"(?<![\w])[~$€£]?\d[\d.,]*\s?"
    r"(?:%|x|k|m|b|bn|million|billion|pts?|points?|hrs?|hours?|h|days?|weeks?|wks?|months?|mos?|years?|yrs?)?",
    re.IGNORECASE,
)


def _metric_of(text: str) -> tuple[str, str, str] | None:
    """Return ``(label, value, detail)`` for a KPI-shaped bullet."""
    label, detail = _split_label(text)
    source = detail or label
    matches = list(_METRIC_RE.finditer(source))
    if not matches:
        return None
    match = matches[0]
    value = match.group(0).strip().rstrip(".,;:")
    if not value or not re.search(r"\d", value):
        return None
    # "Priority 1" is a list index, not a KPI. A bare small number only counts
    # when it is explicitly labelled ("NPS: 5") or carries a unit ("5%", "$5").
    has_unit = bool(
        re.search(
            r"[%$€£xkmb]|(?:pts?|points?|hrs?|hours?|days?|weeks?|mo(?:nths?)?|years?|yrs?)",
            value,
            re.IGNORECASE,
        )
    )
    if len(value) < 3 and not has_unit and ":" not in str(text):
        return None
    if detail:
        # With two figures ("up from 4h to 7h") the whole sentence is the
        # useful context. When the value leads the detail ("2.1%, down from
        # 3.4%") strip it so the card does not repeat itself.
        if len(matches) > 1 and match.start() > 1:
            context = detail
        else:
            context = detail[: match.start()] + detail[match.end() :]
        context = context.strip(" ,.;:-–—")
        return (label or "Metric", value, context)
    context = (source[: match.start()] + source[match.end() :]).strip(" ,.;:-–—")
    return (context[:56] or "Metric", value, "")


def _is_percentage(value: str) -> float | None:
    match = re.fullmatch(r"\s*([\d.]+)\s*%", value)
    if not match:
        return None
    try:
        return max(0.0, min(100.0, float(match.group(1))))
    except ValueError:
        return None


def _chars_per_line(width_in: float, size_pt: float) -> int:
    # Average glyph width for a humanist sans is ~0.5em. This is deliberately
    # conservative so LibreOffice and PowerPoint agree on the line count.
    return max(6, int((width_in * 72) / max(1.0, size_pt * 0.5)))


def _line_count(text: str, width_in: float, size_pt: float) -> int:
    per_line = _chars_per_line(width_in, size_pt)
    total = 0
    for raw in str(text).splitlines() or [""]:
        words = raw.split()
        if not words:
            total += 1
            continue
        line = 0
        rows = 1
        for word in words:
            needed = len(word) + (1 if line else 0)
            if line + needed > per_line and line:
                rows += 1
                line = len(word)
            else:
                line += needed
        total += rows
    return max(1, total)


def _fit_size(
    text: str,
    *,
    width: float,
    height: float,
    base: int = 20,
    minimum: int = 10,
    line_spacing: float = 1.16,
) -> int:
    """Largest font size at which *text* is likely to fit its box."""
    for size in range(int(base), int(minimum) - 1, -1):
        line_h = (size * line_spacing) / 72
        if _line_count(text, width, size) * line_h <= height:
            return size
    return minimum


def _fit_bullets(
    bullets: Iterable[str],
    *,
    width: float,
    height: float,
    base: int = 18,
    minimum: int = 11,
) -> int:
    combined = "\n".join(f"• {bullet}" for bullet in bullets)
    return _fit_size(
        combined, width=width, height=height, base=base, minimum=minimum, line_spacing=1.28
    )


# ── planning stage ─────────────────────────────────────────────────────────
_HEADING_RE = re.compile(r"^#{1,4}\s+(.+)$")
_SLIDE_HEADING_RE = re.compile(r"^slide\s*\d+\s*[:.\-]\s*(.+)$", re.IGNORECASE)
_BULLET_RE = re.compile(r"^\s*(?:[-*+•]|\d+[.)])\s+(.+)$")
_DIVIDER_RE = re.compile(r"^\s*-{3,}\s*$")
_HINT_RE = re.compile(
    r"(?:\[layout:\s*([a-z0-9 _-]+)\]|<!--\s*layout:\s*([a-z0-9 _-]+)\s*-->)",
    re.IGNORECASE,
)
_AGENDA_WORDS = (
    "agenda",
    "what we will cover",
    "what we'll cover",
    "what we cover",
    "contents",
    "today",
)
_CLOSING_WORDS = (
    "thank you",
    "questions",
    "the ask",
    "next steps",
    "recommendation",
    "closing",
    "what we need",
    "discussion",
    "contact",
)
_COMPARISON_WORDS = (
    " before ",
    " after ",
    " versus ",
    " vs ",
    " trade-off ",
    " tradeoffs ",
    " pros and cons ",
    " compare ",
    " comparison ",
    " current vs ",
    " risk ",
    " risks ",
)
_RISK_WORDS = (
    " risk",
    " risks",
    " losing",
    " lost",
    " gap",
    " challenge",
    " headwind",
    " problem",
    " issue",
    " concern",
    " bottleneck",
    " weakness",
    " cost pressure",
    " churn",
)
_TIMELINE_WORDS = (
    "roadmap",
    "timeline",
    "milestone",
    "quarter",
    "quarters",
    "phase",
    "phases",
    "plan",
    "schedule",
    "launch plan",
)
_TIME_PREFIX_RE = re.compile(
    r"^(q[1-4]|h[12]|20\d{2}|19\d{2}|jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|"
    r"may|jun(?:e)?|jul(?:y)?|aug(?:ust)?|sep(?:tember)?|oct(?:ober)?|nov(?:ember)?|"
    r"dec(?:ember)?|phase\s*\d+|week\s*\d+|day\s*\d+|step\s*\d+|now|next|later)\b",
    re.IGNORECASE,
)


def _normalise_slide_list(slides: Any) -> list[tuple[str, list[str], str]]:
    if isinstance(slides, str):
        try:
            import json

            slides = json.loads(slides)
        except (ValueError, TypeError):
            slides = [{"title": "Slide", "bullets": [slides]}]
    if not isinstance(slides, list):
        slides = [{"title": "Slide", "bullets": [str(slides)]}]
    out: list[tuple[str, list[str], str]] = []
    for item in slides:
        if isinstance(item, str):
            out.append((item, [], ""))
        elif isinstance(item, dict):
            bullets = item.get("bullets") or item.get("content") or []
            if isinstance(bullets, str):
                bullets = bullets.splitlines()
            hint = str(item.get("layout") or item.get("_layout") or "").strip().lower()
            out.append(
                (
                    str(item.get("title") or "Slide"),
                    [str(b) for b in bullets if str(b).strip()],
                    hint,
                )
            )
    return out or [("Slide", [], "")]


def parse_outline(
    title: str, content: str = "", slides: Any | None = None
) -> list[tuple[str, list[str], str]]:
    """Stage 1: read a slide list or a Markdown outline."""
    if slides is not None:
        return _normalise_slide_list(slides)

    specs: list[tuple[str, list[str], str]] = []
    current_title = ""
    bullets: list[str] = []
    hint = ""

    def flush() -> None:
        nonlocal current_title, bullets, hint
        if current_title or bullets:
            specs.append((current_title or title or "Slide", bullets, hint))
        current_title, bullets, hint = "", [], ""

    for raw in str(content or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        marker = _HINT_RE.search(line)
        marker_hint = ""
        if marker:
            marker_hint = (
                (marker.group(1) or marker.group(2) or "").strip().lower().replace(" ", "_")
            )
            line = _HINT_RE.sub("", line).strip()
            if not line:
                hint = marker_hint
                continue
        if _DIVIDER_RE.match(line):
            flush()
            continue
        heading = _HEADING_RE.match(line) or _SLIDE_HEADING_RE.match(line)
        if heading:
            flush()
            current_title = heading.group(1).strip()
            hint = marker_hint
            continue
        if marker_hint:
            hint = marker_hint
        bullet = _BULLET_RE.match(line)
        if bullet:
            bullets.append(bullet.group(1).strip())
            continue
        if line.startswith(">"):
            bullets.append(line.lstrip("> ").strip())
            continue
        # Prose in a slide outline is a continuation of the previous bullet,
        # not a new slide. This keeps model chatter from becoming slides.
        if bullets:
            bullets[-1] = f"{bullets[-1]} {line}".strip()
        else:
            bullets.append(line)
    flush()
    return specs or [(title or "Presentation", [], "")]


def _looks_like_section(title: str, bullets: list[str]) -> bool:
    return not bullets


def _infer_layout(title: str, bullets: list[str], hint: str = "", *, is_last: bool = False) -> str:
    if hint:
        cleaned = hint.replace("_", " ").strip()
        aliases = {
            "kpi": "metrics",
            "metric": "metrics",
            "stat": "metrics",
            "stats": "metrics",
            "cards": "cards",
            "card": "cards",
            "comparison": "comparison",
            "compare": "comparison",
            "timeline": "timeline",
            "roadmap": "timeline",
            "agenda": "agenda",
            "quote": "quote",
            "closing": "closing",
            "section": "section",
            "bullets": "bullets",
            "list": "bullets",
        }
        if cleaned in aliases:
            return aliases[cleaned]
    lowered = f" {title.lower()} "
    if _looks_like_section(title, bullets):
        if any(word in lowered for word in _CLOSING_WORDS) and is_last:
            return "closing"
        return "section"
    if any(word in lowered for word in _CLOSING_WORDS) and is_last:
        return "closing"
    if any(word in lowered for word in _AGENDA_WORDS):
        return "agenda"
    if any(word in lowered for word in _RISK_WORDS) and len(bullets) <= 8:
        has_labels = sum(1 for b in bullets if ":" in b or " — " in b or " – " in b) >= 1
        return "cards" if has_labels else "rows"
    metrics = [m for m in (_metric_of(bullet) for bullet in bullets) if m]
    if len(metrics) >= 2 and len(metrics) >= max(2, math.ceil(len(bullets) * 0.6)):
        return "metrics"
    if len(bullets) == 1 and len(bullets[0]) >= 90:
        return "quote"
    if any(word in lowered for word in _COMPARISON_WORDS) and 2 <= len(bullets) <= 8:
        return "comparison"
    if (
        any(word in lowered for word in _TIMELINE_WORDS)
        and 3 <= len(bullets) <= 5
        and sum(1 for b in bullets if _TIME_PREFIX_RE.match(_split_label(b)[0] or b)) >= 2
    ):
        return "timeline"
    if len(bullets) <= 6 and sum(1 for b in bullets if ":" in b or " — " in b or " – " in b) >= 2:
        return "cards"
    if 3 <= len(bullets) <= 5 and all(len(b) <= 110 for b in bullets):
        return "rows"
    if len(bullets) <= 5:
        return "cards"
    return "bullets"


def plan_deck(
    title: str, specs: Iterable[tuple[str, list[str], str]], *, subtitle: str = ""
) -> DeckPlan:
    """Stage 2: clean content, infer layouts and split over-long slides."""
    raw = [
        (str(t or "").strip(), [b for b in bullets if _plain(b)], hint)
        for t, bullets, hint in specs
    ]
    deck_title = _plain(title) or "Presentation"
    cover_subtitle = _plain(subtitle)

    # A leading title-only slide is the deck title; use it for the cover rather
    # than printing the same words twice.
    if raw:
        first_title, first_bullets, _ = raw[0]
        a, b = _slug(first_title), _slug(deck_title)
        if not deck_title or a == b or (b and (a in b or b in a)):
            if first_bullets and not cover_subtitle:
                cover_subtitle = _clip(first_bullets[0], 120)
            raw = raw[1:]

    planned: list[SlidePlan] = []
    body_slides = [item for item in raw if item[0] or item[1]]
    for index, (slide_title, bullets, hint) in enumerate(body_slides):
        is_last = index == len(body_slides) - 1
        title_text = _clip(slide_title, 120) or f"Slide {index + 1}"
        cleaned: list[str] = []
        seen: set[str] = set()
        for bullet in bullets:
            text = _clip(bullet)
            key = _slug(text)
            if text and key not in seen:
                cleaned.append(text)
                seen.add(key)
        layout = _infer_layout(title_text, cleaned, hint, is_last=is_last)

        # Long lists become two slides instead of unreadable micro-text.
        if layout in {"cards", "bullets"} and len(cleaned) > _MAX_BULLETS + 1:
            chunks = [cleaned[i : i + _MAX_BULLETS] for i in range(0, len(cleaned), _MAX_BULLETS)]
            for chunk_index, chunk in enumerate(chunks):
                planned.append(
                    SlidePlan(
                        title=title_text + (" (cont.)" if chunk_index else ""),
                        bullets=tuple(chunk),
                        layout=layout,
                        hint=hint,
                    )
                )
        else:
            planned.append(
                SlidePlan(
                    title=title_text,
                    bullets=tuple(cleaned[: _MAX_BULLETS + 2]),
                    layout=layout,
                    hint=hint,
                )
            )

    # Do not invent a closing slide: the outline is the source of truth. An
    # explicit closing slide is detected above and rendered with the closing
    # layout; otherwise the deck ends where the model ended it.

    return DeckPlan(
        title=deck_title,
        subtitle=cover_subtitle,
        slides=tuple(planned),
    )


# ── drawing primitives ─────────────────────────────────────────────────────
def _rgb(value: str):
    from pptx.dml.color import RGBColor

    return RGBColor.from_string(value)


def _no_shadow(shape) -> None:
    try:
        shape.shadow.inherit = False
    except (AttributeError, ValueError):
        pass
    # python-pptx adds a theme ``p:style`` with an effect reference. LibreOffice
    # and Keynote honour that reference even when effectLst is empty, which is
    # why decks can keep a drop shadow. Remove the style block: every fill and
    # line in this renderer is set explicitly.
    try:
        from pptx.oxml.ns import qn

        element = shape._element
        style = element.find(qn("p:style"))
        if style is not None:
            element.remove(style)
    except (AttributeError, ValueError):
        pass


def _add_text(
    slide,
    text: str,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: int = 14,
    bold: bool = False,
    italic: bool = False,
    color: str = INK,
    align=None,
    anchor=None,
    font: str = FONT,
    line_spacing: float | None = None,
    margins: tuple[float, float, float, float] = (0.02, 0.02, 0.02, 0.02),
):
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    _no_shadow(box)
    frame = box.text_frame
    frame.word_wrap = True
    frame.margin_left = Inches(margins[0])
    frame.margin_right = Inches(margins[1])
    frame.margin_top = Inches(margins[2])
    frame.margin_bottom = Inches(margins[3])
    if anchor is not None:
        frame.vertical_anchor = anchor
    paragraph = frame.paragraphs[0]
    paragraph.text = text
    if align is not None:
        paragraph.alignment = align
    if line_spacing is not None:
        paragraph.line_spacing = line_spacing
    for run in paragraph.runs:
        run.font.name = font
        run.font.size = Pt(size)
        run.font.bold = bold
        run.font.italic = italic
        run.font.color.rgb = _rgb(color)
    return box


def _add_rect(
    slide,
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    fill: str,
    line: str | None = None,
    rounded: bool = False,
    radius: float = 0.08,
    line_width: float = 1.0,
):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches, Pt

    shape_type = MSO_SHAPE.ROUNDED_RECTANGLE if rounded else MSO_SHAPE.RECTANGLE
    shape = slide.shapes.add_shape(shape_type, Inches(x), Inches(y), Inches(w), Inches(h))
    _no_shadow(shape)
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(fill)
    if line:
        shape.line.color.rgb = _rgb(line)
        shape.line.width = Pt(line_width)
    else:
        shape.line.fill.background()
    if rounded:
        try:
            shape.adjustments[0] = radius
        except (IndexError, ValueError):
            pass
    return shape


def _add_circle(slide, x: float, y: float, d: float, *, fill: str, line: str | None = None):
    from pptx.enum.shapes import MSO_SHAPE
    from pptx.util import Inches

    shape = slide.shapes.add_shape(MSO_SHAPE.OVAL, Inches(x), Inches(y), Inches(d), Inches(d))
    _no_shadow(shape)
    shape.fill.solid()
    shape.fill.fore_color.rgb = _rgb(fill)
    if line:
        shape.line.color.rgb = _rgb(line)
    else:
        shape.line.fill.background()
    return shape


def _add_rule(
    slide, x: float, y: float, w: float, *, color: str = LINE, weight: float = 0.012
) -> None:
    _add_rect(slide, x, y, w, weight, fill=color)


def _set_bg(slide, color: str) -> None:
    slide.background.fill.solid()
    slide.background.fill.fore_color.rgb = _rgb(color)


def _add_rich_paragraphs(
    slide,
    items: Iterable[str],
    x: float,
    y: float,
    w: float,
    h: float,
    *,
    size: int,
    color: str = BODY,
    label_color: str = INK_SOFT,
    glyph: str = "▸",
    glyph_color: str = ACCENT,
    gap: float = 8,
    anchor=None,
) -> None:
    from pptx.enum.text import MSO_ANCHOR
    from pptx.util import Inches, Pt

    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    _no_shadow(box)
    frame = box.text_frame
    frame.word_wrap = True
    frame.vertical_anchor = anchor or MSO_ANCHOR.TOP
    frame.margin_left = Inches(0.02)
    frame.margin_right = Inches(0.02)
    frame.margin_top = Inches(0.02)
    frame.margin_bottom = Inches(0.02)
    for index, item in enumerate(items):
        paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
        paragraph.space_after = Pt(gap)
        paragraph.line_spacing = 1.1
        label, detail = _split_label(item)
        marker = paragraph.add_run()
        marker.text = f"{glyph}  "
        marker.font.name = FONT
        marker.font.size = Pt(size)
        marker.font.bold = True
        marker.font.color.rgb = _rgb(glyph_color)
        lead = paragraph.add_run()
        lead.text = label
        lead.font.name = FONT
        lead.font.size = Pt(size)
        lead.font.bold = True
        lead.font.color.rgb = _rgb(label_color)
        if detail:
            rest = paragraph.add_run()
            rest.text = f"  {detail}"
            rest.font.name = FONT
            rest.font.size = Pt(max(10, size - 1))
            rest.font.color.rgb = _rgb(color)


# ── shared slide chrome ────────────────────────────────────────────────────
def _footer(slide, deck: DeckPlan, number: int, total: int) -> None:
    from pptx.enum.text import PP_ALIGN

    _add_rule(slide, 0.72, 6.98, 11.9, color=LINE, weight=0.01)
    _add_text(slide, deck.title[:64], 0.72, 7.06, 8.8, 0.26, size=8.5, color=FAINT)
    _add_text(
        slide,
        f"{number:02d} / {total:02d}",
        11.1,
        7.06,
        1.5,
        0.26,
        size=8.5,
        color=FAINT,
        align=PP_ALIGN.RIGHT,
    )


def _header(slide, slide_title: str, *, eyebrow: str, number: int, total: int) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

    # Progress rail: a quiet visual cue that the deck is moving forward.
    _add_rect(slide, 0, 0, W, 0.07, fill=LINE)
    _add_rect(slide, 0, 0, W * min(1.0, number / max(1, total)), 0.07, fill=ACCENT)
    _add_text(
        slide,
        eyebrow.upper()[:44],
        0.72,
        0.48,
        8.0,
        0.28,
        size=9,
        bold=True,
        color=ACCENT,
    )
    title_size = _fit_size(slide_title, width=10.6, height=0.9, base=30, minimum=20)
    _add_text(
        slide,
        slide_title,
        0.72,
        0.82,
        10.7,
        0.95,
        size=title_size,
        bold=True,
        color=INK,
        font=FONT_DISPLAY,
        anchor=MSO_ANCHOR.TOP,
        line_spacing=0.98,
    )
    _add_rect(slide, 0.72, 1.78, 0.72, 0.055, fill=ACCENT)
    _add_text(
        slide,
        f"{number:02d}",
        12.08,
        0.48,
        0.55,
        0.4,
        size=11,
        bold=True,
        color=MUTED,
        align=PP_ALIGN.RIGHT,
    )


def _content_bg(slide) -> None:
    _set_bg(slide, WHITE)
    # A very faint column keeps the slide from feeling like a blank page.
    _add_rect(slide, 0, 0, 0.1, H, fill=SURFACE)


# ── layouts ────────────────────────────────────────────────────────────────
def _render_cover(prs, deck: DeckPlan) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, DARK)

    # Right-hand stage panel. Rings give the cover depth without an image.
    _add_rect(slide, 9.9, 0, W - 9.9, H, fill=DARK_2)
    _add_rect(slide, 9.9, 0, 0.075, H, fill=ACCENT)
    _add_circle(slide, 10.55, 1.25, 2.3, fill=DARK_2, line=DARK_LINE)
    _add_circle(slide, 11.3, 4.2, 1.45, fill=DARK_2, line=DARK_LINE)
    _add_rect(slide, 10.55, 2.65, 1.9, 0.012, fill=ACCENT)

    _add_text(slide, "PRESENTATION", 0.78, 1.02, 4.0, 0.3, size=10, bold=True, color="93C5FD")
    _add_rect(slide, 0.78, 1.38, 0.86, 0.06, fill=ACCENT)

    title_size = _fit_size(
        deck.title, width=8.45, height=2.3, base=44, minimum=28, line_spacing=1.0
    )
    _add_text(
        slide,
        deck.title,
        0.78,
        1.72,
        8.55,
        2.4,
        size=title_size,
        bold=True,
        color=WHITE,
        font=FONT_DISPLAY,
        anchor=MSO_ANCHOR.TOP,
        line_spacing=0.98,
    )

    subtitle = deck.subtitle or "A working deck built to move the decision forward."
    title_lines = _line_count(deck.title, 8.45, title_size)
    subtitle_y = min(4.7, 1.86 + title_lines * (title_size * 1.05 / 72) + 0.58)
    _add_text(
        slide,
        subtitle,
        0.8,
        subtitle_y,
        7.9,
        1.15,
        size=16,
        color="CBD5E1",
        line_spacing=1.18,
    )
    _add_rule(slide, 0.8, 5.95, 6.2, color=DARK_LINE, weight=0.012)
    _add_text(
        slide,
        "Prepared with PaliMind · local-first workspace",
        0.8,
        6.15,
        6.0,
        0.3,
        size=9,
        color=FAINT,
    )
    _add_text(
        slide,
        "01",
        10.15,
        5.3,
        2.2,
        1.05,
        size=52,
        bold=True,
        color="1E3A8A",
        align=PP_ALIGN.RIGHT,
    )
    _add_text(
        slide,
        "PALIMIND",
        10.15,
        0.62,
        2.2,
        0.3,
        size=9,
        bold=True,
        color="60A5FA",
        align=PP_ALIGN.RIGHT,
    )
    _footer(slide, deck, 1, max(1, len(deck.slides) + 1))


def _render_section(
    prs,
    deck: DeckPlan,
    plan: SlidePlan,
    number: int,
    total: int,
    *,
    next_title: str = "",
) -> None:
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, DARK)
    _add_rect(slide, 0, 0, 0.16, H, fill=ACCENT)
    _add_text(
        slide, f"SECTION {number:02d}", 0.98, 2.05, 3.0, 0.35, size=10, bold=True, color="93C5FD"
    )
    title_size = _fit_size(
        plan.title, width=10.2, height=2.1, base=40, minimum=26, line_spacing=1.0
    )
    _add_text(
        slide,
        plan.title,
        0.98,
        2.48,
        10.4,
        2.1,
        size=title_size,
        bold=True,
        color=WHITE,
        font=FONT_DISPLAY,
        anchor=MSO_ANCHOR.TOP,
        line_spacing=0.98,
    )
    if next_title:
        _add_text(slide, "UP NEXT", 0.98, 5.45, 2.0, 0.28, size=8.5, bold=True, color="60A5FA")
        _add_text(
            slide,
            next_title[:90],
            0.98,
            5.74,
            7.8,
            0.4,
            size=12,
            color="CBD5E1",
        )
    _add_rule(slide, 0.98, 6.3, 1.3, color=ACCENT, weight=0.05)
    _add_text(
        slide,
        f"{number:02d}",
        10.4,
        5.1,
        2.1,
        1.05,
        size=54,
        bold=True,
        color="1E3A8A",
    )
    _footer(slide, deck, number, total)


def _render_agenda(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    from pptx.enum.text import MSO_ANCHOR, PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _content_bg(slide)
    _header(slide, plan.title, eyebrow="Agenda", number=number, total=total)
    items = list(plan.bullets)[:6]
    columns = 2 if len(items) > 4 else 1
    per_column = math.ceil(len(items) / max(1, columns))
    col_w = (11.9 - 0.55) / columns if columns == 2 else 9.4
    row_h = min(1.18, 4.55 / max(1, per_column))
    for index, item in enumerate(items):
        column = index // per_column
        row = index % per_column
        x = 0.78 + column * (col_w + 0.55)
        y = 1.98 + row * row_h
        label, detail = _split_label(item)
        _add_text(
            slide,
            f"{index + 1:02d}",
            x,
            y + 0.04,
            0.55,
            0.32,
            size=12,
            bold=True,
            color=ACCENT,
            align=PP_ALIGN.LEFT,
        )
        text_w = col_w - 0.72
        fitted = _fit_size(
            label + (f" — {detail}" if detail else ""),
            width=text_w,
            height=row_h - 0.1,
            base=17,
            minimum=12,
        )
        _add_text(
            slide,
            label,
            x + 0.66,
            y,
            text_w,
            0.36,
            size=fitted,
            bold=True,
            color=INK_SOFT,
            anchor=MSO_ANCHOR.TOP,
        )
        if detail:
            _add_text(
                slide,
                detail[:150],
                x + 0.66,
                y + 0.34,
                text_w,
                row_h - 0.36,
                size=max(10, fitted - 4),
                color=MUTED,
                anchor=MSO_ANCHOR.TOP,
            )
        if row < per_column - 1:
            _add_rule(slide, x, y + row_h - 0.1, col_w - 0.15, color=LINE, weight=0.008)
    if not items:
        _add_text(
            slide, "Add the agenda points in the outline.", 0.78, 2.1, 6, 0.5, size=14, color=MUTED
        )
    _footer(slide, deck, number, total)


def _render_metrics(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _content_bg(slide)
    _header(slide, plan.title, eyebrow="Key numbers", number=number, total=total)
    metrics = [m for m in (_metric_of(b) for b in plan.bullets) if m][:4]
    count = max(1, len(metrics))
    gap = 0.26
    left, top = 0.78, 2.02
    width = (11.9 - gap * (count - 1)) / count
    height = 3.55
    for index, (label, value, detail) in enumerate(metrics):
        x = left + index * (width + gap)
        _add_rect(slide, x, top, width, height, fill=CARD, line=LINE, rounded=True, radius=0.07)
        _add_rect(
            slide, x + 0.28, top + 0.28, 0.34, 0.05, fill=ACCENT if index % 2 == 0 else VIOLET
        )
        value_size = 36 if len(value) <= 6 else 30 if len(value) <= 9 else 24
        _add_text(
            slide,
            value,
            x + 0.28,
            top + 0.58,
            width - 0.5,
            0.9,
            size=value_size,
            bold=True,
            color=INK,
            font=FONT_DISPLAY,
            anchor=MSO_ANCHOR.TOP,
        )
        _add_text(
            slide,
            label[:60],
            x + 0.28,
            top + 1.55,
            width - 0.5,
            0.55,
            size=13,
            bold=True,
            color=INK_SOFT,
            anchor=MSO_ANCHOR.TOP,
        )
        if detail:
            _add_text(
                slide,
                detail[:90],
                x + 0.28,
                top + 2.03,
                width - 0.5,
                0.8,
                size=10.5,
                color=MUTED,
                anchor=MSO_ANCHOR.TOP,
                line_spacing=1.1,
            )
        pct = _is_percentage(value)
        if pct is not None:
            track_w = width - 0.56
            _add_rect(
                slide,
                x + 0.28,
                top + height - 0.46,
                track_w,
                0.08,
                fill="E2E8F0",
                rounded=True,
                radius=0.5,
            )
            fill_w = max(0.12, track_w * (pct / 100.0))
            _add_rect(
                slide,
                x + 0.28,
                top + height - 0.46,
                fill_w,
                0.08,
                fill=ACCENT if index % 2 == 0 else VIOLET,
                rounded=True,
                radius=0.5,
            )
    # A takeaway row turns the numbers into a point of view.
    if metrics:
        first = metrics[0]
        takeaway = f"{first[0]}: {first[1]}" + (f" · {first[2]}" if first[2] else "")
        _add_text(
            slide,
            takeaway[:150],
            0.8,
            5.92,
            10.5,
            0.42,
            size=11,
            italic=True,
            color=MUTED,
        )
    _footer(slide, deck, number, total)


def _render_cards(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _content_bg(slide)
    _header(slide, plan.title, eyebrow="What matters", number=number, total=total)
    items = [str(b) for b in plan.bullets if str(b).strip()][:6]
    columns = 2 if len(items) <= 4 else 3
    rows = max(1, math.ceil(len(items) / columns))
    gap_x, gap_y = 0.22, 0.2
    left, top = 0.78, 1.96
    total_w, total_h = 11.9, 4.35
    card_w = (total_w - gap_x * (columns - 1)) / columns
    card_h = (total_h - gap_y * (rows - 1)) / rows
    for index, item in enumerate(items):
        column, row = index % columns, index // columns
        x = left + column * (card_w + gap_x)
        y = top + row * (card_h + gap_y)
        _add_rect(slide, x, y, card_w, card_h, fill=CARD, line=LINE, rounded=True, radius=0.07)
        _add_rect(slide, x + 0.24, y + 0.25, 0.38, 0.05, fill=ACCENT if index % 2 == 0 else VIOLET)
        _add_text(
            slide,
            f"{index + 1:02d}",
            x + card_w - 0.6,
            y + 0.18,
            0.38,
            0.25,
            size=9,
            bold=True,
            color=FAINT,
        )
        label, detail = _split_label(item)
        fitted = _fit_size(label, width=card_w - 0.5, height=0.72, base=16, minimum=12)
        _add_text(
            slide,
            label[:100],
            x + 0.24,
            y + 0.46,
            card_w - 0.48,
            0.72,
            size=fitted,
            bold=True,
            color=INK_SOFT,
            anchor=MSO_ANCHOR.TOP,
            line_spacing=1.02,
        )
        if detail:
            detail_size = _fit_size(
                detail,
                width=card_w - 0.5,
                height=card_h - 1.35,
                base=11.5,
                minimum=9.5,
            )
            _add_text(
                slide,
                detail,
                x + 0.24,
                y + 1.27,
                card_w - 0.48,
                card_h - 1.4,
                size=detail_size,
                color=BODY,
                anchor=MSO_ANCHOR.TOP,
                line_spacing=1.08,
            )
    if not items:
        _add_text(
            slide,
            "Add the supporting points in the outline.",
            0.8,
            2.1,
            6,
            0.5,
            size=14,
            color=MUTED,
        )
    _footer(slide, deck, number, total)


def _comparison_parts(plan: SlidePlan) -> tuple[str, str, list[str], list[str]]:
    lowered = f" {plan.title.lower()} "
    if " before " in lowered:
        left_label, right_label = "Before", "After"
    elif " risk " in lowered or " risks " in lowered:
        left_label, right_label = "Risk", "Mitigation"
    elif "current" in lowered and ("proposed" in lowered or "proposal" in lowered):
        left_label, right_label = "Current", "Proposed"
    elif " vs " in lowered or " versus " in lowered:
        left_label, right_label = "Option A", "Option B"
    else:
        left_label, right_label = "Current", "Proposed"

    left: list[str] = []
    right: list[str] = []
    for bullet in plan.bullets:
        label, detail = _split_label(bullet)
        key = label.lower()
        if key in {"current", "before", "today", "problem", "risk", "option a", "pros", "weakness"}:
            left.append(detail or label)
        elif key in {
            "proposed",
            "after",
            "next",
            "solution",
            "mitigation",
            "option b",
            "cons",
            "fix",
        }:
            right.append(detail or label)
        else:
            (right if len(left) > len(right) else left).append(bullet)
    if not left or not right:
        midpoint = max(1, len(plan.bullets) // 2)
        left, right = list(plan.bullets[:midpoint]), list(plan.bullets[midpoint:])
    return left_label, right_label, left[:5], right[:5]


def _render_comparison(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _content_bg(slide)
    _header(slide, plan.title, eyebrow="Comparison", number=number, total=total)
    left_label, right_label, left_items, right_items = _comparison_parts(plan)
    panels = (
        (left_label, left_items, CARD, MUTED, "E2E8F0", "✕"),
        (right_label, right_items, CARD_ALT, ACCENT, ACCENT_SOFT, "✓"),
    )
    panel_w = (11.9 - 0.32) / 2
    for index, (label, items, fill, accent, border, glyph) in enumerate(panels):
        x = 0.78 + index * (panel_w + 0.32)
        y, h = 1.98, 3.95
        _add_rect(slide, x, y, panel_w, h, fill=fill, line=border, rounded=True, radius=0.06)
        _add_rect(
            slide,
            x,
            y,
            panel_w,
            0.55,
            fill=accent if index else "CBD5E1",
            rounded=True,
            radius=0.06,
        )
        _add_text(
            slide,
            label.upper(),
            x + 0.28,
            y + 0.15,
            panel_w - 0.5,
            0.3,
            size=10,
            bold=True,
            color=WHITE if index else INK_SOFT,
        )
        body = [str(item) for item in items if str(item).strip()]
        if body:
            size = _fit_bullets(body, width=panel_w - 0.65, height=h - 0.95, base=15, minimum=10.5)
            _add_rich_paragraphs(
                slide,
                body,
                x + 0.3,
                y + 0.78,
                panel_w - 0.55,
                h - 0.95,
                size=size,
                glyph=glyph,
                glyph_color=accent,
                gap=10,
                anchor=MSO_ANCHOR.MIDDLE,
            )
        else:
            _add_text(
                slide, "No items yet.", x + 0.3, y + 0.9, panel_w - 0.6, 0.4, size=12, color=MUTED
            )
    _footer(slide, deck, number, total)


def _timeline_parts(bullets: Iterable[str]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for index, bullet in enumerate(bullets):
        label, detail = _split_label(bullet)
        if _TIME_PREFIX_RE.match(label):
            stamp = label
            title = detail or label
            description = "" if detail else ""
            out.append((stamp.upper(), title[:90], description[:130]))
        elif _TIME_PREFIX_RE.match(detail):
            match = _TIME_PREFIX_RE.match(detail)
            stamp = match.group(0).strip() if match else f"0{index + 1}"
            rest = detail[match.end() :].strip(" :-–—") if match else detail
            out.append((stamp.upper(), (label or rest)[:90], rest[:130]))
        else:
            out.append((f"0{index + 1}", label[:90], detail[:130]))
    return out


def _render_timeline(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    from pptx.enum.text import PP_ALIGN

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _content_bg(slide)
    _header(slide, plan.title, eyebrow="Timeline", number=number, total=total)
    items = _timeline_parts(plan.bullets)[:5]
    count = max(1, len(items))
    left, right = 1.55, 11.75
    rail_y = 3.35
    _add_rect(slide, left, rail_y, right - left, 0.045, fill=LINE)
    _add_rect(
        slide,
        left,
        rail_y,
        max(0.1, (right - left) * (count - 1) / max(1, count - 1)),
        0.045,
        fill=ACCENT,
    )
    step = (right - left) / max(1, count - 1) if count > 1 else 0
    text_w = min(2.55, (right - left) / max(1, count) + 0.42)
    for index, (stamp, title, detail) in enumerate(items):
        cx = left + index * step if count > 1 else (left + right) / 2
        cx = min(max(cx, text_w / 2 + 0.25), W - text_w / 2 - 0.25)
        _add_circle(
            slide,
            cx - 0.11,
            rail_y - 0.085,
            0.22,
            fill=ACCENT if index % 2 == 0 else VIOLET,
            line=WHITE,
        )
        _add_text(
            slide,
            stamp,
            cx - text_w / 2,
            rail_y - 0.68,
            text_w,
            0.32,
            size=11,
            bold=True,
            color=ACCENT if index % 2 == 0 else VIOLET,
            align=PP_ALIGN.CENTER,
        )
        _add_text(
            slide,
            title,
            cx - text_w / 2,
            rail_y + 0.32,
            text_w,
            0.9,
            size=14 if count <= 4 else 12.5,
            bold=True,
            color=INK_SOFT,
            align=PP_ALIGN.CENTER,
            line_spacing=1.02,
        )
        if detail:
            _add_text(
                slide,
                detail,
                cx - text_w / 2,
                rail_y + 1.16,
                text_w,
                1.15,
                size=10.5,
                color=MUTED,
                align=PP_ALIGN.CENTER,
                line_spacing=1.06,
            )
    _footer(slide, deck, number, total)


def _render_quote(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, SURFACE)
    _add_rect(slide, 0, 0, 0.16, H, fill=ACCENT)
    _add_text(slide, "“", 0.78, 1.0, 1.2, 1.2, size=84, color=ACCENT_SOFT, font="Georgia")
    quote = _plain(plan.bullets[0]) if plan.bullets else plan.title
    size = _fit_size(quote, width=10.6, height=2.8, base=28, minimum=18, line_spacing=1.22)
    _add_text(
        slide,
        quote,
        0.92,
        2.05,
        11.2,
        2.9,
        size=size,
        italic=True,
        color=INK_SOFT,
        font="Georgia",
        anchor=MSO_ANCHOR.TOP,
        line_spacing=1.18,
    )
    _add_rule(slide, 0.94, 5.45, 1.1, color=ACCENT, weight=0.05)
    _add_text(slide, plan.title[:90], 0.94, 5.62, 10.6, 0.38, size=12, bold=True, color=MUTED)
    _footer(slide, deck, number, total)


def _render_closing(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _set_bg(slide, DARK)
    _add_rect(slide, 0, 0, W, 0.08, fill=ACCENT)
    _add_text(slide, "NEXT", 0.82, 1.18, 3.0, 0.32, size=10, bold=True, color="93C5FD")
    title = plan.title or "Next steps"
    size = _fit_size(title, width=10.8, height=1.4, base=38, minimum=24, line_spacing=1.0)
    _add_text(
        slide,
        title,
        0.82,
        1.58,
        10.9,
        1.5,
        size=size,
        bold=True,
        color=WHITE,
        font=FONT_DISPLAY,
        anchor=MSO_ANCHOR.TOP,
        line_spacing=0.98,
    )
    items = list(plan.bullets)[:5]
    if items:
        start_y = 3.35
        row_h = min(0.62, (6.05 - start_y) / max(1, len(items)))
        for index, item in enumerate(items):
            y = start_y + index * row_h
            _add_text(
                slide,
                f"{index + 1:02d}",
                0.86,
                y + 0.02,
                0.5,
                0.3,
                size=10,
                bold=True,
                color="60A5FA",
            )
            label, detail = _split_label(item)
            _add_text(
                slide,
                (label + (" — " + detail if detail else ""))[:180],
                1.5,
                y - 0.04,
                10.2,
                row_h - 0.04,
                size=14,
                color="E2E8F0",
                anchor=MSO_ANCHOR.TOP,
            )
            _add_rule(slide, 0.86, y + row_h - 0.08, 10.9, color=DARK_LINE, weight=0.008)
    else:
        _add_text(
            slide,
            "Questions, decisions and owners — capture them before the room clears.",
            0.84,
            3.5,
            10.6,
            0.8,
            size=15,
            color="CBD5E1",
        )
    _add_text(slide, deck.title[:70], 0.84, 6.72, 8.4, 0.28, size=8.5, color=FAINT)
    _add_text(slide, f"{number:02d} / {total:02d}", 11.0, 6.72, 1.6, 0.28, size=8.5, color=FAINT)


def _render_rows(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    """Short, unlabelled lists become a clean numbered stack."""
    from pptx.enum.text import MSO_ANCHOR

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _content_bg(slide)
    lowered = plan.title.lower()
    eyebrow = (
        "Watchlist"
        if any(word.strip() in lowered for word in _RISK_WORDS)
        else "Priorities"
        if any(word in lowered for word in ("priority", "priorities", "plan", "next"))
        else "At a glance"
    )
    _header(slide, plan.title, eyebrow=eyebrow, number=number, total=total)
    items = [str(item) for item in plan.bullets if str(item).strip()][:5]
    if not items:
        _add_text(
            slide,
            "Add the supporting points in the outline.",
            0.8,
            2.1,
            6,
            0.5,
            size=14,
            color=MUTED,
        )
        _footer(slide, deck, number, total)
        return
    gap = 0.16
    top, available = 1.98, 4.78
    height = (available - gap * (len(items) - 1)) / len(items)
    for index, item in enumerate(items):
        y = top + index * (height + gap)
        _add_rect(
            slide,
            0.78,
            y,
            11.9,
            height,
            fill=CARD if index % 2 == 0 else WHITE,
            line=LINE,
            rounded=True,
            radius=0.05,
        )
        _add_rect(slide, 0.78, y, 0.075, height, fill=ACCENT if index % 2 == 0 else VIOLET)
        _add_text(
            slide,
            f"{index + 1:02d}",
            1.06,
            y + (height - 0.34) / 2,
            0.55,
            0.34,
            size=11,
            bold=True,
            color=MUTED,
        )
        label, detail = _split_label(item)
        text = label + (f" — {detail}" if detail else "")
        size = _fit_size(text, width=10.3, height=height - 0.18, base=16, minimum=11)
        _add_text(
            slide,
            text,
            1.78,
            y + (height - 0.45) / 2,
            10.5,
            max(0.4, height - 0.18),
            size=size,
            bold=True,
            color=INK_SOFT,
            anchor=MSO_ANCHOR.MIDDLE,
            line_spacing=1.02,
        )
    _footer(slide, deck, number, total)


def _render_bullets(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:

    slide = prs.slides.add_slide(prs.slide_layouts[6])
    _content_bg(slide)
    _header(slide, plan.title, eyebrow="Detail", number=number, total=total)
    items = [str(b) for b in plan.bullets][:12]
    columns = 2 if len(items) > 5 else 1
    gap = 0.45
    width = (11.9 - gap) / columns
    per_column = math.ceil(len(items) / columns)
    for column in range(columns):
        chunk = items[column * per_column : (column + 1) * per_column]
        if not chunk:
            continue
        size = _fit_bullets(chunk, width=width - 0.1, height=4.75, base=16, minimum=10.5)
        _add_rich_paragraphs(
            slide,
            chunk,
            0.78 + column * (width + gap),
            1.98,
            width,
            4.75,
            size=size,
            gap=9,
        )
    _footer(slide, deck, number, total)


def _render_content(prs, deck: DeckPlan, plan: SlidePlan, number: int, total: int) -> None:
    renderer = {
        "agenda": _render_agenda,
        "metrics": _render_metrics,
        "cards": _render_cards,
        "rows": _render_rows,
        "comparison": _render_comparison,
        "timeline": _render_timeline,
        "quote": _render_quote,
        "closing": _render_closing,
        "bullets": _render_bullets,
    }.get(plan.layout, _render_bullets)
    renderer(prs, deck, plan, number, total)


# ── public pipeline ────────────────────────────────────────────────────────
def render_deck(deck: DeckPlan) -> bytes:
    """Stage 3: draw every planned slide into a valid .pptx file."""
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    prs.slide_width = Inches(W)
    prs.slide_height = Inches(H)
    try:
        prs.core_properties.title = deck.title
        prs.core_properties.author = "PaliMind"
        prs.core_properties.comments = "Designed with the PaliMind presentation pipeline."
    except Exception:
        pass

    total = len(deck.slides) + 1
    _render_cover(prs, deck)
    for index, plan in enumerate(deck.slides, start=2):
        if plan.layout == "section":
            next_title = deck.slides[index - 1].title if index - 1 < len(deck.slides) else ""
            _render_section(prs, deck, plan, index, total, next_title=next_title)
        else:
            _render_content(prs, deck, plan, index, total)

    buffer = io.BytesIO()
    prs.save(buffer)
    return buffer.getvalue()


def validate_deck(data: bytes, *, expected_slides: int | None = None) -> list[str]:
    """Stage 4: cheap structural checks on the rendered bytes.

    Returns warnings rather than raising so a valid file is never discarded
    because a cosmetic expectation changed.
    """
    warnings: list[str] = []
    try:
        from pptx import Presentation

        prs = Presentation(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001 - callers surface a clear error
        return [f"not a readable presentation: {exc}"]
    slides = list(prs.slides)
    if not slides:
        warnings.append("deck has no slides")
    if expected_slides is not None and len(slides) != expected_slides:
        warnings.append(f"expected {expected_slides} slides, found {len(slides)}")
    for index, slide in enumerate(slides, start=1):
        texts = [
            str(getattr(shape, "text", "") or "")
            for shape in slide.shapes
            if getattr(shape, "has_text_frame", False)
        ]
        if not any(text.strip() for text in texts):
            warnings.append(f"slide {index} has no text")
    return warnings


def build_deck(
    title: str,
    content: str = "",
    slides: Any | None = None,
    *,
    subtitle: str = "",
) -> tuple[bytes, DeckPlan, list[str]]:
    """Run the full presentation pipeline and return bytes + plan + warnings."""
    specs = parse_outline(title, content, slides)
    plan = plan_deck(title, specs, subtitle=subtitle)
    data = render_deck(plan)
    warnings = validate_deck(data, expected_slides=len(plan.slides) + 1)
    return data, plan, warnings
