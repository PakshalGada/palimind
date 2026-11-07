"""Annotation + OCR fallback tests for computer use."""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from palimind.agents.tools.desktop import annotation


def _white(path: Path, size=(200, 150)) -> Path:
    Image.new("RGB", size, (255, 255, 255)).save(path)
    return path


def test_ref_boxes_match_snapshot_bounds_within_one_pixel(tmp_path):
    source = _white(tmp_path / "shot.png")
    snapshot = {
        "bounds_space": "screen",
        "window": {"bounds": {"x": 0, "y": 0, "width": 200, "height": 150}},
        "nodes": [
            {
                "ref": "@s1:e7",
                "role": "button",
                "name": "Save",
                "bounds": [10.0, 20.0, 30.0, 40.0],
            },
            {"ref": None, "role": "group", "name": "container", "bounds": [0, 0, 200, 150]},
        ],
    }
    path, annotations = annotation.annotate_image(source, snapshot)
    assert Path(path).exists()
    assert len(annotations) == 1
    assert annotations[0]["ref"] == "@s1:e7"
    assert annotations[0]["box"] == [10, 20, 40, 60]

    # The inverse transform must recover the snapshot bounds within tolerance.
    box = annotations[0]["box"]
    recovered = [box[0], box[1], box[2] - box[0], box[3] - box[1]]
    assert all(abs(a - b) <= 1 for a, b in zip(recovered, snapshot["nodes"][0]["bounds"], strict=False))

    # A rectangle was actually painted.
    image = Image.open(path).convert("RGB")
    assert image.getpixel((10, 20)) != (255, 255, 255)
    assert image.getpixel((39, 59)) != (255, 255, 255)


def test_scale_and_crop_offset_transform_correctly(tmp_path):
    source = _white(tmp_path / "shot.png", size=(200, 150))
    snapshot = {
        "bounds_space": "screen",
        "window": {"bounds": {"x": 0, "y": 0, "width": 200, "height": 150}},
        "nodes": [
            {
                "ref": "@s1:e1",
                "role": "button",
                "name": "OK",
                "bounds": [10.0, 20.0, 30.0, 40.0],
            }
        ],
    }
    _, annotations = annotation.annotate_image(
        source, snapshot, scale=2.0, offset=(20.0, 10.0)
    )
    assert annotations[0]["box"] == [0, 30, 60, 110]


def test_window_relative_bounds_add_the_window_origin(tmp_path):
    source = _white(tmp_path / "shot.png", size=(300, 200))
    snapshot = {
        "bounds_space": "window",
        "window": {"bounds": {"x": 100, "y": 50, "width": 100, "height": 100}},
        "nodes": [
            {
                "ref": "@s1:e2",
                "role": "button",
                "name": "7",
                "bounds": [10.0, 20.0, 30.0, 40.0],
            }
        ],
    }
    _, annotations = annotation.annotate_image(source, snapshot)
    assert annotations[0]["box"] == [110, 70, 140, 110]


def test_window_bounds_with_no_proven_origin_are_refused(tmp_path):
    source = _white(tmp_path / "shot.png")
    snapshot = {
        "bounds_space": "window",
        "window": {"bounds": {"x": 0, "y": 0, "width": 200, "height": 150}},
        "nodes": [{"ref": "@s1:e1", "role": "button", "bounds": [10, 20, 30, 40]}],
    }
    import pytest

    with pytest.raises(ValueError, match="proven screen origin"):
        annotation.annotate_image(source, snapshot)


def test_ocr_boxes_are_labelled_and_not_stable(tmp_path, monkeypatch):
    source = _white(tmp_path / "shot.png")

    class FakeReader:
        def readtext(self, _image, detail=1, paragraph=False):
            return [
                (
                    [[10, 10], [60, 10], [60, 30], [10, 30]],
                    "Save  changes",
                    0.91,
                )
            ]

    import palimind.ingestion.ocr as ocr_module

    monkeypatch.setattr(ocr_module, "get_reader", lambda gpu=True: FakeReader())
    boxes = annotation.ocr_boxes(source, scale=2.0, offset=(4.0, 6.0))
    assert boxes[0]["ref"] == "ocr:0"
    assert boxes[0]["kind"] == "ocr"
    assert boxes[0]["text"] == "Save changes"
    assert boxes[0]["stable"] is False
    assert boxes[0]["image_box"] == [10, 10, 50, 20]
    assert boxes[0]["bounds"] == [7.0, 8.0, 25.0, 10.0]

    drawn = annotation.draw_ocr_boxes(source, boxes)
    assert Path(drawn).exists()


def test_annotation_refuses_nothing_when_no_bounds_are_present(tmp_path):
    source = _white(tmp_path / "shot.png")
    _, annotations = annotation.annotate_image(
        source, {"bounds_space": "unknown", "nodes": [{"ref": "@s1:e1"}]}
    )
    assert annotations == []
