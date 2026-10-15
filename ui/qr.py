"""QR codes (make and read). Both need an optional package and fall back gracefully: the code text is always shown too."""
import io
from typing import Optional


def png_bytes(text: str, scale: int = 8) -> Optional[bytes]:
    try:
        import segno
        buffer = io.BytesIO()
        segno.make(text, error="m").save(buffer, kind="png", scale=scale, border=2, dark="#7A1F2B")
        return buffer.getvalue()
    except Exception:  # noqa: BLE001
        return None


def read(image_bytes: bytes) -> Optional[str]:
    """Reads the text of a QR code from a photo. Returns None if nothing could be read."""
    try:
        import cv2
        import numpy as np
        frame = cv2.imdecode(np.frombuffer(image_bytes, np.uint8), cv2.IMREAD_COLOR)
        if frame is None:
            return None
        text, _points, _raw = cv2.QRCodeDetector().detectAndDecode(frame)
        return text or None
    except Exception:  # noqa: BLE001
        return None


def donor_card_text(donor) -> str:
    """The text inside a donor's QR card. The check-in screen understands it (see app/routes/checkin_routes.py)."""
    name = (donor.full_name or "").replace("|", " ")
    return f"LIFEFLOW-DONOR|id:{donor.id}|name:{name}|type:{donor.blood_type}"
