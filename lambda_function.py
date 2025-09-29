import os
import json
import tempfile
import boto3
from datetime import datetime
from playwright.sync_api import sync_playwright

s3 = boto3.client("s3")

# Config via env
SRC_BUCKET  = os.getenv("SRC_BUCKET")
DEST_BUCKET = os.getenv("DEST_BUCKET")
BASE_PREFIX = os.getenv("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.getenv("PDF_FORMAT", "A4")

# Make fontconfig cache writable (gets rid of those "No writable cache" errors)
os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp/.cache")
os.makedirs("/tmp/.cache/fontconfig", exist_ok=True)

def _prefix_from_event(event: dict) -> str:
    # event may provide year/month override
    year  = str(event.get("year")  or datetime.utcnow().year)
    month = str(event.get("month") or f"{datetime.utcnow().month:02d}")
    return f"{BASE_PREFIX.rstrip('/')}/{year}/{month}/"

def _debug_on(event: dict) -> bool:
    v = event.get("debug")
    if isinstance(v, (int, float)):
        return bool(v)
    if isinstance(v, str):
        return v.strip().lower() in ("1","true","yes","y","on")
    return False

def lambda_handler(event, context):
    try:
        prefix = _prefix_from_event(event or {})
        html_key = f"{prefix}uptime-report.html"
        pdf_key  = f"{prefix}uptime-report.pdf"

        # 1) Get HTML from source bucket
        src_bucket = SRC_BUCKET
        if not src_bucket or not DEST_BUCKET:
            return _err(500, "Missing SRC_BUCKET or DEST_BUCKET env")

        html_obj = s3.get_object(Bucket=src_bucket, Key=html_key)
        html = html_obj["Body"].read().decode("utf-8")

        # 2) Save HTML to /tmp and render with Chromium → PDF
        with tempfile.TemporaryDirectory() as tdir:
            html_path = os.path.join(tdir, "in.html")
            pdf_path  = os.path.join(tdir, "out.pdf")
            with open(html_path, "w", encoding="utf-8") as f:
                f.write(html)

            with sync_playwright() as p:
                browser = p.chromium.launch(
                    headless=True,
                    args=[
                        "--headless=new",
                        "--no-sandbox",
                        "--disable-setuid-sandbox",
                        "--disable-gpu",
                        "--disable-dev-shm-usage",
                        "--no-zygote",
                        "--single-process",
                        "--mute-audio",
                        "--hide-scrollbars",
                        "--font-render-hinting=none"
                    ],
                )
                try:
                    ctx = browser.new_context(
                        viewport={"width": 1440, "height": 900},
                        device_scale_factor=2,   # crisper text
                        java_script_enabled=True,
                    )
                    page = ctx.new_page()

                    # Prefer file:// to avoid network policy surprises; your HTML is self-contained
                    page.goto(f"file://{html_path}", wait_until="networkidle", timeout=120_000)

                    page.pdf(
                        path=pdf_path,
                        format=PDF_FORMAT,
                        print_background=True,
                        prefer_css_page_size=True,
                        margin={"top":"0.4in","right":"0.4in","bottom":"0.6in","left":"0.4in"},
                        scale=1.0
                    )
                finally:
                    browser.close()

            # 3) Upload PDF + (optionally) re-upload HTML into dest bucket
            with open(pdf_path, "rb") as f:
                s3.put_object(Bucket=DEST_BUCKET, Key=pdf_key, Body=f, ContentType="application/pdf")
            # Keep your previous behavior of copying HTML to dest too:
            s3.put_object(Bucket=DEST_BUCKET, Key=f"{prefix}uptime-report.html", Body=html.encode("utf-8"),
                          ContentType="text/html; charset=utf-8")

        if _debug_on(event or {}):
            return _ok({
                "src_bucket": SRC_BUCKET,
                "dest_bucket": DEST_BUCKET,
                "prefix": prefix,
                "html_key": html_key,
                "dest_pdf_key": pdf_key
            })

        # Normal response (API Gateway/Lambda proxy shape)
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"ok": True, "pdf": f"s3://{DEST_BUCKET}/{pdf_key}"})
        }

    except Exception as e:
        return _err(500, f"PDF generation failed: {e}")

def _ok(obj: dict):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(obj),
    }

def _err(code: int, msg: str):
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }
