from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from scripts.cover_health import analyze_cover


class CoverHealthTests(unittest.TestCase):
    def test_black_cover_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "black.jpg"
            Image.new("RGB", (1080, 1920), (0, 0, 0)).save(path)

            result = analyze_cover(path)

            self.assertEqual(result["status"], "fail")
            self.assertIn("p95_luma_ok", result["errors"])

    def test_readable_cover_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cover.jpg"
            image = Image.new("RGB", (1080, 1920), (18, 22, 28))
            draw = ImageDraw.Draw(image)
            draw.rectangle((80, 160, 1000, 430), fill=(255, 214, 10))
            draw.rectangle((80, 520, 1000, 980), fill=(250, 250, 245))
            draw.rectangle((80, 1180, 840, 1320), fill=(114, 231, 255))
            image.save(path, quality=95)

            result = analyze_cover(path)

            self.assertEqual(result["status"], "pass", result)

    def test_readable_horizontal_cover_passes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "horizontal.jpg"
            image = Image.new("RGB", (1920, 1080), (18, 22, 28))
            draw = ImageDraw.Draw(image)
            draw.rectangle((120, 120, 840, 320), fill=(255, 214, 10))
            draw.rectangle((120, 400, 1480, 760), fill=(250, 250, 245))
            draw.rectangle((120, 860, 680, 980), fill=(114, 231, 255))
            image.save(path, quality=95)

            result = analyze_cover(path)

            self.assertEqual(result["status"], "pass", result)


if __name__ == "__main__":
    unittest.main()
