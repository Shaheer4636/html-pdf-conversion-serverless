# lambda_function.py
import os
import json
import tempfile
from urllib.parse import parse_qs
import boto3
from playwright.sync_api import sync_playwright

# -------- ENV VARS (all optional; sensible defaults) --------
SRC_BUCKET       = os.environ.get("SRC_BUCKET", "lambda-output-report-000000987123")
DEST_BUCKET      = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX      = os.environ.get("BASE_PREFIX", "uptime")
REGION           = os.environ.get("REGION")  # not required by boto3 in Lambda, but accepted
HTML_NAME        = os.environ.get("HTML_NAME", "uptime-report")   # without extension
PDF_NAME         = os.environ.get("PDF_NAME", HTML_NAME)          # without extension
PDF_FORMAT       = os.environ.get("PDF_FORMAT", "A4")             # A4 | Letter | etc.
LANDSCAPE        = os.environ.get("LANDSCAPE", "false")
MARGIN_TOP       = os.environ.get("MARGIN_TOP", "0mm")
MARGIN_RIGHT     = os.environ.get("MARGIN_RIGHT", "0mm")
MARGIN_BOTTOM    = os.environ.get("MARGIN_BOTTOM", "0mm")
MARGIN_LEFT      = os.environ.get("MARGIN_LEFT", "0mm")
PREFER_CSS_SIZE  = os.environ.get("PREFER_CSS_PAGE_SIZE", "true")
PRINT_BG         = os.environ.get("PRINT_BACKGROUND", "true")
EMULATE_MEDIA    = os.environ.get("EMULATE_MEDIA", "print")       # print | screen
PLAYWRIGHT_WAIT  = os.environ.get("PLAYWRIGHT_WAIT", "networkidle")# load|domcontentloaded|networkidle
VIEWPORT_WIDTH   = os.environ.get("VIEWPORT_WIDTH", "1366")
VIEWPORT_HEIGHT  = os.environ.get("VIEWPORT_HEIGHT", "768")
DEVICE_SCALE     = os.environ.get("DEVICE_SCALE", "1.0")
ALLOW_PDF_SKIP   = os.environ.get("ALLOW_PDF_SKIP", "false")      # if true, skip render if pdf exists and html older
CHROMIUM_ARGS    = os.environ.get("CHROMIUM_ARGS", "")            # extra --flags separated by spaces

# Make caches writable in Lambda
os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

S3 = boto3.client("s3", region_name=REGION) if REGION else boto3.client("s3")

def _as_bool(v: str, default=False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in ("1", "true", "yes", "y", "on")

def _as_int(v: str, default: int) -> int:
    try:
        return int(float(str(v).strip()))
    except Exception:
        return default

def _as_float(v: str, default: float) -> float:
    try:
        return float(str(v).strip())
    except Exception:
        return default

def _wait_mode(v: str) -> str:
    v = (v or "").strip().lower()
    return v if v in ("load", "domcontentloaded", "networkidle", "commit") else "networkidle"

def _key(year: str, month: str, name: str, ext: str) -> str:
    return f"{BASE_PREFIX}/{year}/{month}/{name}.{ext}"

def _resp(code: int, body: dict):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }

def _extract_event(event: dict):
    """Support direct Lambda, API GW (v1/v2), and test payloads."""
    year = None
    month = None
    debug = None

    if isinstance(event, dict):
        # direct keys
        year = event.get("year") or year
        month = event.get("month") or month
        debug = event.get("debug") if "debug" in event else debug

        # API GW v2 rawQueryString
        raw_qs = event.get("rawQueryString")
        if raw_qs:
            qs = parse_qs(raw_qs)
            year = year or (qs.get("year", [None])[0])
            month = month or (qs.get("month", [None])[0])
            debug = debug if debug is not None else (qs.get("debug", [None])[0])

        # API GW v1/v2 structured
        qsp = event.get("queryStringParameters")
        if isinstance(qsp, dict):
            year = year or qsp.get("year")
            month = month or qsp.get("month")
            debug = qsp.get("debug") if debug is None else debug

    # defaults if missing
    year = str(year or "2025").zfill(4)
    month = str(month or "09").zfill(2)
    dbg = _as_bool("" if debug is None else str(debug), False)
    return year, month, dbg

def _pdf_exists_is_fresh(html_bucket, html_key, pdf_bucket, pdf_key) -> bool:
    try:
        pdf_head = S3.head_object(Bucket=pdf_bucket, Key=pdf_key)
    except Exception:
        return False
    try:
        html_head = S3.head_object(Bucket=html_bucket, Key=html_key)
    except Exception:
        return False
    return pdf_head["LastModified"] >= html_head["LastModified"]

def lambda_handler(event, context):
    year, month, want_debug = _extract_event(event or {})

    html_key = _key(year, month, HTML_NAME, "html")
    pdf_key  = _key(year, month, PDF_NAME, "pdf")

    if want_debug:
        return _resp(200, {
            "env": {
                "SRC_BUCKET": SRC_BUCKET, "DEST_BUCKET": DEST_BUCKET, "BASE_PREFIX": BASE_PREFIX,
                "REGION": REGION, "HTML_NAME": HTML_NAME, "PDF_NAME": PDF_NAME,
                "PDF_FORMAT": PDF_FORMAT, "LANDSCAPE": LANDSCAPE,
                "MARGINS": [MARGIN_TOP, MARGIN_RIGHT, MARGIN_BOTTOM, MARGIN_LEFT],
                "PREFER_CSS_PAGE_SIZE": PREFER_CSS_SIZE, "PRINT_BACKGROUND": PRINT_BG,
                "EMULATE_MEDIA": EMULATE_MEDIA, "PLAYWRIGHT_WAIT": PLAYWRIGHT_WAIT,
                "VIEWPORT": [VIEWPORT_WIDTH, VIEWPORT_HEIGHT], "DEVICE_SCALE": DEVICE_SCALE,
                "ALLOW_PDF_SKIP": ALLOW_PDF_SKIP, "CHROMIUM_ARGS": CHROMIUM_ARGS
            },
            "keys": {
                "src_html": f"s3://{SRC_BUCKET}/{html_key}",
                "dest_pdf": f"s3://{DEST_BUCKET}/{pdf_key}"
            }
        })

    # Optional: skip if already fresh
    if _as_bool(ALLOW_PDF_SKIP, False) and _pdf_exists_is_fresh(SRC_BUCKET, html_key, DEST_BUCKET, pdf_key):
        return _resp(200, {
            "skipped": True,
            "reason": "Existing PDF is up-to-date",
            "dest_pdf_key": pdf_key
        })

    # Work paths
    os.makedirs("/tmp", exist_ok=True)
    html_path = os.path.join(tempfile.gettempdir(), "report.html")

    try:
        # 1) Download HTML
        S3.download_file(SRC_BUCKET, html_key, html_path)

        # 2) Render with Chromium (Ctrl+P fidelity)
        vp_w = _as_int(VIEWPORT_WIDTH, 1366)
        vp_h = _as_int(VIEWPORT_HEIGHT, 768)
        dpr  = _as_float(DEVICE_SCALE, 1.0)
        wait_until = _wait_mode(PLAYWRIGHT_WAIT)

        launch_args = [
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--force-color-profile=srgb",
            "--export-tagged-pdf",
            "--no-zygote",
        ]
        extra = [a for a in CHROMIUM_ARGS.split(" ") if a.strip()]
        launch_args.extend(extra)

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=launch_args)
            context = browser.new_context(
                viewport={"width": vp_w, "height": vp_h},
                device_scale_factor=dpr,
                java_script_enabled=True,
                color_scheme="light",
                accept_downloads=False,
            )
            page = context.new_page()

            # Emulate desired media
            page.emulate_media(media=(EMULATE_MEDIA if EMULATE_MEDIA in ("print", "screen") else "print"))

            # Load file URL
            page.goto(f"file://{html_path}", wait_until=wait_until)

            # PDF options
            pdf_bytes = page.pdf(
                print_background=_as_bool(PRINT_BG, True),
                prefer_css_page_size=_as_bool(PREFER_CSS_SIZE, True),
                format=PDF_FORMAT,
                margin={
                    "top": MARGIN_TOP,
                    "right": MARGIN_RIGHT,
                    "bottom": MARGIN_BOTTOM,
                    "left": MARGIN_LEFT
                },
                landscape=_as_bool(LANDSCAPE, False),
            )

            context.close()
            browser.close()

        # 3) Upload PDF
        S3.put_object(
            Bucket=DEST_BUCKET,
            Key=pdf_key,
            Body=pdf_bytes,
            ContentType="application/pdf"
        )

        return _resp(200, {
            "src_bucket": SRC_BUCKET,
            "dest_bucket": DEST_BUCKET,
            "prefix": f"{BASE_PREFIX}/{year}/{month}/",
            "html_key": html_key,
            "dest_pdf_key": pdf_key
        })

    except Exception as e:
        return _resp(500, {"error": f"PDF generation failed: {e}"})
