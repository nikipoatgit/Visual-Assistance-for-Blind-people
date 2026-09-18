"""Single-frame pipeline: quality check -> YOLO bus detect -> ROI -> OCR -> parse.

Models are loaded lazily and kept in module-level globals, so they are
initialised exactly once for the lifetime of the process.
"""

import re

import cv2
import numpy as np
from rapidfuzz import process as fuzz

import config
import status

_model = None
_reader = None


# --------------------------------------------------------------------------
# Lazy model loading
# --------------------------------------------------------------------------
def get_model():
    global _model
    if _model is None:
        from ultralytics import YOLO
        _model = YOLO(config.MODEL_NAME)
    return _model


def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        _reader = easyocr.Reader(config.OCR_LANGS, gpu=False, verbose=False)
    return _reader


def warmup():
    """Load both models before the first frame arrives."""
    blank = np.zeros((320, 320, 3), dtype=np.uint8)
    get_model().predict(blank, verbose=False)
    get_reader().readtext(blank)
    status.mark_warmup_done()


# --------------------------------------------------------------------------
# Stage 1 - quality
# --------------------------------------------------------------------------
def quality_check(bgr):
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    brightness = float(gray.mean())
    blur = float(cv2.Laplacian(gray, cv2.CV_64F).var())

    if brightness < config.DARK_THRESHOLD:
        return False, "too dark"
    if brightness > config.BRIGHT_THRESHOLD:
        return False, "too bright"
    if blur < config.BLUR_THRESHOLD:
        return False, "blurry"
    return True, "ok"


# --------------------------------------------------------------------------
# Stage 2 - bus detection
# --------------------------------------------------------------------------
def detect_bus(bgr):
    """Return (crop, confidence) for the largest confident bus, else (None, 0)."""
    res = get_model().predict(
        bgr,
        imgsz=config.YOLO_IMGSZ,
        conf=config.YOLO_CONF,
        classes=[config.BUS_CLASS_ID],
        verbose=False,
    )[0]

    best, best_area = None, 0
    for box in res.boxes:
        x1, y1, x2, y2 = (int(v) for v in box.xyxy[0].tolist())
        area = (x2 - x1) * (y2 - y1)
        if area > best_area:
            best_area = area
            best = (x1, y1, x2, y2, float(box.conf[0]))

    if best is None:
        return None, 0.0

    x1, y1, x2, y2, conf = best
    h, w = bgr.shape[:2]
    x1, y1 = max(0, x1), max(0, y1)
    x2, y2 = min(w, x2), min(h, y2)
    crop = bgr[y1:y2, x1:x2]
    if crop.size == 0:
        return None, 0.0
    return crop, conf


# --------------------------------------------------------------------------
# Stage 3 - OCR
# --------------------------------------------------------------------------
def _ocr(image):
    if image is None or image.size == 0:
        return []
    if max(image.shape[:2]) < 480:          # upscale small crops for EasyOCR
        image = cv2.resize(image, None, fx=2.0, fy=2.0,
                           interpolation=cv2.INTER_CUBIC)
    out = []
    for _box, text, conf in get_reader().readtext(image):
        if conf >= config.OCR_MIN_CONF and text.strip():
            out.append((text.strip().upper(), float(conf)))
    return out


def read_sign(bus_crop):
    """OCR the upper board first; fall back to the whole bus if it comes back empty."""
    h = bus_crop.shape[0]
    board = bus_crop[: max(1, int(h * config.ROI_TOP_RATIO)), :]
    texts = _ocr(board)
    if not texts:
        texts = _ocr(bus_crop)
    return texts


# --------------------------------------------------------------------------
# Stage 4 - parsing
# --------------------------------------------------------------------------
def parse_texts(texts):
    route, destination = None, None
    route_conf, dest_conf = 0.0, 0.0

    for text, conf in texts:
        if route is None:
            m = re.search(config.ROUTE_PATTERN, text)
            if m and any(c.isdigit() for c in m.group(0)):
                route, route_conf = m.group(0), conf

        if destination is None:
            hit = fuzz.extractOne(
                text, config.DESTINATIONS,
                score_cutoff=config.DEST_MATCH_CUTOFF,
            )
            if hit:
                destination, dest_conf = hit[0], conf

    confs = [c for c in (route_conf, dest_conf) if c]
    return route, destination, (sum(confs) / len(confs) if confs else 0.0)


# --------------------------------------------------------------------------
# Public entry point - one RGB frame in, one result dict out
# --------------------------------------------------------------------------
def process_frame(frame_rgb):
    """frame_rgb: numpy RGB array from Gradio. Returns a result dict."""
    bgr = cv2.cvtColor(frame_rgb, cv2.COLOR_RGB2BGR)

    ok, reason = quality_check(bgr)
    if not ok:
        result = {"status": "QUALITY_ERROR", "reason": reason,
                  "bus_number": None, "destination": None, "confidence": 0.0}
        status.record_frame(result)
        return result

    crop, yolo_conf = detect_bus(bgr)
    if crop is None:
        result = {"status": "NO_DETECTION", "reason": "no bus",
                  "bus_number": None, "destination": None, "confidence": 0.0}
        status.record_frame(result)
        return result

    texts = read_sign(crop)
    route, dest, ocr_conf = parse_texts(texts)
    ocr_texts = [t for t, _ in texts]

    if route is None and dest is None:
        result = {"status": "OCR_ERROR", "reason": "sign unreadable",
                  "bus_number": None, "destination": None,
                  "confidence": round(yolo_conf, 2)}
        status.record_frame(result, ocr_texts)
        return result

    result = {
        "status": "SUCCESS",
        "reason": "",
        "bus_number": route,
        "destination": dest,
        "confidence": round((yolo_conf + ocr_conf) / 2, 2),
    }
    status.record_frame(result, ocr_texts)
    return result
