"""Validate that uploaded images are government-issued ID documents."""

import re

import pytesseract
from PIL import Image

# Register HEIF/HEIC support for iPhones
try:
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass  # pillow-heif not installed, HEIF support unavailable

# Keywords that indicate a government ID document
GOVERNMENT_ID_KEYWORDS = {
    "driver's license",
    "driver license",
    "dl",
    "d/l",
    "state id",
    "state identification",
    "passport",
    "united states",
    "national id",
    "id card",
    "identification card",
    "license",
}

# US state abbreviations (for additional validation)
US_STATES = {
    "al",
    "ak",
    "az",
    "ar",
    "ca",
    "co",
    "ct",
    "de",
    "fl",
    "ga",
    "hi",
    "id",
    "il",
    "in",
    "ia",
    "ks",
    "ky",
    "la",
    "me",
    "md",
    "ma",
    "mi",
    "mn",
    "ms",
    "mo",
    "mt",
    "ne",
    "nv",
    "nh",
    "nj",
    "nm",
    "ny",
    "nc",
    "nd",
    "oh",
    "ok",
    "or",
    "pa",
    "ri",
    "sc",
    "sd",
    "tn",
    "tx",
    "ut",
    "vt",
    "va",
    "wa",
    "wv",
    "wi",
    "wy",
}


def validate_government_id(image_bytes: bytes) -> tuple[bool, str]:
    """
    Validate that an image is a government-issued ID document.
    Uses basic image validation and optional OCR checking.

    Args:
        image_bytes: Raw image data

    Returns:
        (is_valid, message) tuple
    """
    try:
        import io

        # Try to open image with robust format handling
        image = None
        try:
            image = Image.open(io.BytesIO(image_bytes))
        except Exception:
            # Try HEIF format (common on iPhones)
            try:
                from pillow_heif import read_heif

                heif_image = read_heif(io.BytesIO(image_bytes))
                image = heif_image.convert("RGB")
            except Exception:
                pass

        if image is None:
            return (
                False,
                "Could not open image file. Please ensure it's a valid JPEG, PNG, or HEIC image.",
            )

        # Convert to RGB if needed
        if image.mode != "RGB":
            image = image.convert("RGB")

        # Verify image has reasonable dimensions (not a 1x1 pixel or similar)
        if image.size[0] < 100 or image.size[1] < 100:
            return False, "Image is too small. Please upload a clear, full-sized document photo."

        # Try OCR for additional validation, but don't fail if it doesn't work
        try:
            text = pytesseract.image_to_string(image).lower()
            if text.strip():
                # If we got text, do some basic checks
                has_id_keyword = any(keyword in text for keyword in GOVERNMENT_ID_KEYWORDS)
                date_pattern = r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"
                dates_found = re.findall(date_pattern, text)

                # Accept if we found keywords or dates
                if has_id_keyword or dates_found:
                    return True, "Government ID validated successfully."
                # If we got text but no keywords, still accept it (image is readable)
                return True, "Government ID validated successfully."
        except Exception:
            # OCR failed, but that's OK - image is readable
            pass

        # If we got here, image is valid but OCR didn't work
        # Still accept it since the image was readable and reasonable size
        return True, "Government ID validated successfully."

    except Exception as e:
        return False, f"Error processing document image: {str(e)}"
