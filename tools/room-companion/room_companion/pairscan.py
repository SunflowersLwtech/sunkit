"""Reading the owner's pairing code (docs/e2ee.md) off a camera frame: the QR code the HipiMind page shows.

Needs zxing-cpp and Pillow (the `scan` extra). Without them `available()` is False, and pairing takes the code
as text (`e2ee-pair --code`). A frame is decoded in memory and dropped: nothing here writes it anywhere, and
nothing here logs what a QR code says (a pairing code holds a one-time secret).
"""
from __future__ import annotations

import io

from . import e2ee

try:
    import zxingcpp
except ImportError:  # pragma: no cover - the decoder is optional
    zxingcpp = None
try:
    from PIL import Image
except ImportError:  # pragma: no cover - Pillow is optional
    Image = None

#: Frames larger than this are decoded at a reduced scale (JPEG draft mode): a code held up to the camera
#: is large in the picture, and a 4K frame decoded in full would only cost time.
MAX_SIDE = 1920


def available() -> bool:
    return zxingcpp is not None and Image is not None


def pairing_code_in(jpeg: bytes) -> tuple[str | None, int]:
    """The text of the first pairing code among the QR codes in a JPEG frame, or None; and how many other QR
    codes (anything `e2ee.parse_pairing_code` refuses) were ignored."""
    if not available() or not jpeg:
        return None, 0
    try:
        with Image.open(io.BytesIO(jpeg)) as im:
            longest = max(im.size)
            if longest > MAX_SIDE:
                im.draft("L", (max(1, im.width * MAX_SIDE // longest), max(1, im.height * MAX_SIDE // longest)))
            gray = im.convert("L")
        found = zxingcpp.read_barcodes(gray, formats=zxingcpp.BarcodeFormat.QRCode)
    except Exception:  # a damaged frame, or one the decoder cannot read: no code in it
        return None, 0
    ignored = 0
    for barcode in found:
        text = barcode.text
        try:
            e2ee.parse_pairing_code(text)
        except e2ee.PairingRefused:
            ignored += 1
            continue
        return text, ignored
    return None, ignored
