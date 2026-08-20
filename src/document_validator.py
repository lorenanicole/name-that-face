"""Validate that uploaded images are government-issued ID documents."""

import re

import cv2
import numpy as np
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

        # Check if image contains a detectable face (required for ID)
        try:
            # Convert PIL image to OpenCV format
            cv_image = cv2.cvtColor(np.array(image), cv2.COLOR_RGB2BGR)

            # Use Haar cascade to detect faces
            cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
            face_cascade = cv2.CascadeClassifier(cascade_path)
            gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
            faces = face_cascade.detectMultiScale(
                gray, scaleFactor=1.1, minNeighbors=5, minSize=(30, 30)
            )

            if len(faces) == 0:
                return (
                    False,
                    "No face detected in image. Government ID must show a clear photo of a person's face.",
                )
        except Exception:
            # Face detection failed, continue with text validation
            pass

        # Perform OCR validation - REQUIRED for government IDs
        try:
            text = pytesseract.image_to_string(image).lower()
            if not text.strip():
                return (
                    False,
                    "No readable text found in document. Please ensure the ID is clear and legible.",
                )

            # Check for government ID keywords
            has_id_keyword = any(keyword in text for keyword in GOVERNMENT_ID_KEYWORDS)
            if not has_id_keyword:
                return (
                    False,
                    "Document does not appear to be a government-issued ID. Please upload a passport, driver's license, or state ID.",
                )

            # Check for date (expiration or issue date)
            date_pattern = r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{4})\b"
            dates_found = re.findall(date_pattern, text)
            if not dates_found:
                return (
                    False,
                    "No date found on document. Please ensure the ID contains a visible expiration or issue date.",
                )

            return True, "Government ID validated successfully."
        except Exception as e:
            return False, f"Could not read document text. Error: {str(e)}"

    except Exception as e:
        return False, f"Error processing document image: {str(e)}"
