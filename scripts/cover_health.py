#!/usr/bin/env python3
"""Pixel-level checks for Searchpo cover images.

The uploader can report success even when Douyin falls back to a black video
frame. This script catches local black/blank covers before artifact binding and
can also be reused for remote listing screenshots.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class CoverThresholds:
    min_width: int = 720
    min_height: int = 1280
    min_mean_luma: float = 24.0
    min_p95_luma: float = 72.0
    min_bright_ratio: float = 0.012
    min_contrast: float = 90.0


def _load_pil():
    try:
        from PIL import Image
    except Exception as exc:  # pragma: no cover - dependency presence is env-specific
        raise RuntimeError("Pillow is required for cover health checks. Install PIL/Pillow for this Python.") from exc
    return Image


def _percentile(values: list[int], percentile: float) -> float:
    if not values:
        return 0.0
    index = min(len(values) - 1, max(0, round((len(values) - 1) * percentile)))
    return float(values[index])


def analyze_cover(path: Path, thresholds: CoverThresholds | None = None) -> dict[str, Any]:
    thresholds = thresholds or CoverThresholds()
    image_lib = _load_pil()
    path = path.expanduser().resolve()
    if not path.is_file():
        return {
            "status": "fail",
            "path": str(path),
            "errors": [f"cover image missing: {path}"],
        }

    with image_lib.open(path) as image:
        rgb = image.convert("RGB")
        width, height = rgb.size
        sample = rgb.resize((min(width, 270), min(height, 480)))
        lumas = sorted(round((r * 0.2126) + (g * 0.7152) + (b * 0.0722)) for r, g, b in sample.getdata())

    mean_luma = sum(lumas) / len(lumas) if lumas else 0.0
    p95_luma = _percentile(lumas, 0.95)
    bright_ratio = sum(1 for value in lumas if value >= 76) / len(lumas) if lumas else 0.0
    contrast = float((lumas[-1] - lumas[0]) if lumas else 0)

    checks = {
        "size_ok": width >= thresholds.min_width and height >= thresholds.min_height,
        "mean_luma_ok": mean_luma >= thresholds.min_mean_luma,
        "p95_luma_ok": p95_luma >= thresholds.min_p95_luma,
        "bright_ratio_ok": bright_ratio >= thresholds.min_bright_ratio,
        "contrast_ok": contrast >= thresholds.min_contrast,
    }
    errors = [name for name, ok in checks.items() if not ok]
    return {
        "status": "pass" if not errors else "fail",
        "path": str(path),
        "width": width,
        "height": height,
        "bytes": path.stat().st_size,
        "mean_luma": round(mean_luma, 3),
        "p95_luma": round(p95_luma, 3),
        "bright_ratio": round(bright_ratio, 5),
        "contrast": round(contrast, 3),
        "checks": checks,
        "errors": errors,
    }


def assert_cover_healthy(path: Path, thresholds: CoverThresholds | None = None) -> dict[str, Any]:
    result = analyze_cover(path, thresholds)
    if result["status"] != "pass":
        raise RuntimeError(f"cover health check failed for {path}: {', '.join(result.get('errors') or [])}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("cover", help="Cover image to inspect")
    parser.add_argument("--json-out", help="Optional output JSON path")
    args = parser.parse_args()

    result = analyze_cover(Path(args.cover))
    if args.json_out:
        output = Path(args.json_out)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
