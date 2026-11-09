"""Screenshot annotation and local OCR for computer use.

Two rules from the plan drive this module:

* screenshots are opt-in and local-only;
* OCR boxes are *not* stable refs. They are labelled ``ocr:<n>``, carry a
  confidence, and an action on one needs explicit confirmation.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

_DEFAULT_BOX = (255, 64, 64)
_OCR_BOX = (255, 196, 64)
_LABEL_BG = (20, 22, 28)


def _font() -> ImageFont.ImageFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(path, 11)
        except OSError:
            continue
    return ImageFont.load_default()


def _int_box(bounds: list[Any]) -> tuple[int, int, int, int]:
    x, y, width, height = (float(value) for value in bounds[:4])
    return int(round(x)), int(round(y)), int(round(width)), int(round(height))


def snapshot_annotations(
    snapshot: dict[str, Any],
    *,
    scale: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> list[dict[str, Any]]:
    """Map accessibility node bounds to annotated image pixels.

    ``offset`` is the crop origin in physical pixels (region selection). Node
    bounds are logical screen/window coordinates; they are scaled, shifted by
    the window origin for window-local snapshots, then shifted by the crop
    origin.
    """

    window = snapshot.get("window") or {}
    window_bounds = window.get("bounds") or {}
    window_x = float(window_bounds.get("x") or 0.0)
    window_y = float(window_bounds.get("y") or 0.0)
    space = snapshot.get("bounds_space") or "unknown"
    annotations: list[dict[str, Any]] = []
    for node in snapshot.get("nodes") or []:
        ref = node.get("ref")
        bounds = node.get("bounds")
        if not ref or not isinstance(bounds, list) or len(bounds) != 4:
            continue
        x, y, width, height = _int_box(bounds)
        if space == "window":
            x += int(round(window_x))
            y += int(round(window_y))
        box = (
            int(round(x * scale - offset[0])),
            int(round(y * scale - offset[1])),
            int(round((x + width) * scale - offset[0])),
            int(round((y + height) * scale - offset[1])),
        )
        annotations.append(
            {
                "ref": ref,
                "role": node.get("role"),
                "name": node.get("name"),
                "bounds": bounds,
                "bounds_space": space,
                "box": list(box),
            }
        )
    return annotations


def annotate_image(
    path: str | Path,
    snapshot: dict[str, Any] | None,
    *,
    scale: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
    output_path: str | Path | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Draw ref boxes on a screenshot and return the new path + annotation map."""

    if snapshot and snapshot.get("bounds_space") == "window":
        window = snapshot.get("window") or {}
        window_bounds = window.get("bounds") or {}
        # On Wayland the compositor does not expose a global window origin; a
        # window-local rectangle cannot be placed on a display screenshot. An
        # origin of 0,0 is the ambiguous case: it may be a maximized window or
        # an unproven origin, so refuse rather than mislabel the image.
        if (
            float(window_bounds.get("x") or 0.0) == 0.0
            and float(window_bounds.get("y") or 0.0) == 0.0
        ):
            raise ValueError(
                "window-local accessibility bounds have no proven screen origin; "
                "annotate on X11 or use OCR boxes instead"
            )

    source = Path(path)
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _font()
    annotations = snapshot_annotations(snapshot or {}, scale=scale, offset=offset)
    for annotation in annotations:
        left, top, right, bottom = annotation["box"]
        if right <= left or bottom <= top:
            continue
        draw.rectangle((left, top, right, bottom), outline=_DEFAULT_BOX, width=2)
        label = f"{annotation['ref'].rsplit(':', 1)[-1]} {annotation['role'] or ''}".strip()
        text_box = draw.textbbox((left, top), label, font=font)
        label_top = max(0, top - (text_box[3] - text_box[1]) - 4)
        draw.rectangle(
            (left, label_top, left + (text_box[2] - text_box[0]) + 6, top),
            fill=_LABEL_BG,
        )
        draw.text((left + 3, label_top + 1), label, fill=(255, 220, 220), font=font)
    target = Path(output_path) if output_path else source.with_name(source.stem + "-annotated.png")
    image.save(target, format="PNG")
    return str(target), annotations


def ocr_boxes(
    path: str | Path,
    *,
    scale: float = 1.0,
    offset: tuple[float, float] = (0.0, 0.0),
) -> list[dict[str, Any]]:
    """Run the existing local easyocr path and return ``ocr:<n>`` boxes.

    Coordinates are translated back to logical screen coordinates so a caller
    can use them with ``desktop_act(x=..., y=..., coords_source="screenshot")``.
    """

    import numpy as np

    from palimind.ingestion.ocr import get_reader

    image = Image.open(path).convert("RGB")
    reader = get_reader(gpu=True)
    results = reader.readtext(np.array(image), detail=1, paragraph=False)
    boxes: list[dict[str, Any]] = []
    for index, entry in enumerate(results):
        try:
            points, text, confidence = entry
        except (TypeError, ValueError):
            continue
        text = " ".join(str(text).split())
        if not text:
            continue
        xs = [float(point[0]) for point in points]
        ys = [float(point[1]) for point in points]
        left = min(xs) + offset[0]
        top = min(ys) + offset[1]
        width = max(xs) - min(xs)
        height = max(ys) - min(ys)
        boxes.append(
            {
                "ref": f"ocr:{index}",
                "kind": "ocr",
                "text": text,
                "confidence": round(float(confidence), 3),
                "image_box": [
                    int(round(min(xs))),
                    int(round(min(ys))),
                    int(round(width)),
                    int(round(height)),
                ],
                "bounds": [
                    round(left / scale, 1),
                    round(top / scale, 1),
                    round(width / scale, 1),
                    round(height / scale, 1),
                ],
                "bounds_space": "screen",
                "stable": False,
            }
        )
    return boxes


def draw_ocr_boxes(
    path: str | Path,
    boxes: list[dict[str, Any]],
    output_path: str | Path | None = None,
) -> str:
    """Draw ``ocr:<n>`` labels on the image for visual debugging."""

    source = Path(path)
    image = Image.open(source).convert("RGB")
    draw = ImageDraw.Draw(image)
    font = _font()
    for box in boxes:
        x, y, width, height = box["image_box"]
        draw.rectangle((x, y, x + width, y + height), outline=_OCR_BOX, width=2)
        label = f"{box['ref']} {box['text'][:28]}"
        draw.text((x, max(0, y - 12)), label, fill=(255, 230, 180), font=font)
    target = Path(output_path) if output_path else source.with_name(source.stem + "-ocr.png")
    image.save(target, format="PNG")
    return str(target)
