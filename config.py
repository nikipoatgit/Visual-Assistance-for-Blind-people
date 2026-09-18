"""All tunable constants live here. No data files, no JSON, no .txt lists."""

# ---------- Camera / cycle ----------
STREAM_EVERY = 0.1          # seconds between frames sent to Python (~10 FPS)
FRAMES_PER_CYCLE = 10       # frames voted on before an announcement (~1 second worth)

# ---------- Image quality (OpenCV) ----------
DARK_THRESHOLD = 40         # mean gray below this -> too dark
BRIGHT_THRESHOLD = 225      # mean gray above this -> washed out
BLUR_THRESHOLD = 50.0       # Laplacian variance below this -> blurry
QUALITY_FAIL_LIMIT = 3      # failures per cycle that trigger a quality warning

# ---------- YOLOv8 ----------
MODEL_NAME = "yolov8n.pt"   # auto-downloaded on first run, kept next to app.py
BUS_CLASS_ID = 5            # COCO class id for "bus"
YOLO_CONF = 0.35
YOLO_IMGSZ = 640

# ---------- ROI / OCR ----------
ROI_TOP_RATIO = 0.45        # destination board sits in the upper part of the bus
OCR_MIN_CONF = 0.30
OCR_LANGS = ["en"]

# ---------- Text parsing ----------
ROUTE_PATTERN = r"\b[A-Z]{0,2}\d{1,4}[A-Z]?\b"
DEST_MATCH_CUTOFF = 72      # RapidFuzz score needed to accept a destination

DESTINATIONS = [
    "Downtown",
    "Central Station",
    "Airport",
    "Railway Station",
    "City Center",
    "Bus Terminal",
    "University",
    "Hospital",
]

# ---------- Server ----------
SERVER_NAME = "0.0.0.0"     # bind on all interfaces so the phone can reach it
SERVER_PORT = 7860

# ---------- HTTPS (self-signed) ----------
# Point these at a cert/key pair to serve https:// directly instead of relying
# on SHARE=1 or a browser insecure-origin flag. See generate_cert.sh.
# If either file is missing, the app falls back to plain http://.
SSL_CERTFILE = "cert.pem"
SSL_KEYFILE = "key.pem"

# ---------- HTTP -> HTTPS redirect ----------
# Whenever a cert/key is present (HTTPS is active on SERVER_PORT), also bind a
# tiny plain-HTTP listener on HTTP_REDIRECT_PORT that 301-redirects everything
# to https://<same-host>:SERVER_PORT<same-path>. This is what lets someone type
# a plain http:// LAN address (or the browser's default port 80) on the phone
# and land on https:// automatically instead of getting a refused connection
# or a camera-blocked insecure page.
ENABLE_HTTP_REDIRECT = True
HTTP_REDIRECT_PORT = 80        # standard http port; needs a privilege grant on
                                 # Ubuntu (see generate_cert.sh / README note),
                                 # falls back to HTTP_REDIRECT_FALLBACK_PORT
HTTP_REDIRECT_FALLBACK_PORT = 8080
