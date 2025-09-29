# lambda_function.py
# HTML → PDF in Lambda using Playwright (Chromium)
# - Reads latest src HTML from S3 under uptime/<year>/<month>/.../uptime-report.html
# - Copies HTML to dest bucket
# - Renders PDF with headless Chromium and uploads to dest bucket
# - Supports ?month=09&year=2025&debug=1 (also works with event JSON)
#
# Required in the container image:
#   pip install playwright==1.46.*
#   python -m playwright install chromium
# Plus OS libs (already in your Dockerfile for AL2023).

import json
import os
import fnmatch
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

# ---------- config (env overrides) ----------
SRC_BUCKET   = os.getenv("SRC_BUCKET",   "lambda-output-report-000000987123")
DEST_BUCKET  = os.getenv("DEST_BUCKET",  "pdf-uptime-reports-0000009")
BASE_PREFIX  = os.getenv("BASE_PREFIX",  "uptime")

SRC_FILE_NAME = os.getenv("SRC_FILE_NAME", "uptime-report.html")  # file to search for
OUT_HTML_NAME = os.getenv("OUT_HTML_NAME", "uptime-report.html")  # copy name on dest
OUT_PDF_NAME  = os.getenv("OUT_PDF_NAME",  "uptime-report.pdf")   # pdf name on dest

PDF_FORMAT   = os.getenv("PDF_FORMAT", "A4")  # A4 | Letter | Legal | etc.
WAIT_MODE    = os.getenv("PLAYWRIGHT_WAIT", "load").lower()  # load | domcontentloaded | networkidle
ALLOW_PDF_SKIP = (os.getenv("ALLOW_PDF_SKIP", "false").lower() in ("1", "true", "yes"))
PAGE_TIMEOUT_MS = int(os.getenv("PAGE_TIMEOUT_MS", "60000"))

# ---------- clients ----------
s3 = boto3.client("s3")


# ---------- lambda entry ----------
def lambda_handler(event, context):
    """Main handler"""
    try:
        month_str, year_str = _resolve_month_year(event)
    except ValueError as ve:
        return _error(400, str(ve))

    prefix = f"{BASE_PREFIX}/{year_str}/{month_str}/"
    html_key      = f"{prefix}{SRC_FILE_NAME}"
    dest_html_key = f"{prefix}{OUT_HTML_NAME}"
    dest_pdf_key  = f"{prefix}{OUT_PDF_NAME}"

    debug = _want_debug(event or {})

    # Find newest uptime-report.html under prefix (either exact or any subfolder/*/uptime-report.html)
    try:
        latest_obj = _find_latest_report(SRC_BUCKET, prefix)
        if latest_obj is None:
            return _error(
                404,
                f'No "{SRC_FILE_NAME}" found under s3://{SRC_BUCKET}/{prefix} (including subfolders).'
            )

        src_key = latest_obj["Key"]
        print(f"[src] using: s3://{SRC_BUCKET}/{src_key}")

        obj = s3.get_object(Bucket=SRC_BUCKET, Key=src_key)
        html = obj["Body"].read().decode("utf-8", errors="replace")

    except ClientError as e:
        msg = e.response.get("Error", {}).get("Message", str(e))
        return _error(500, f"S3 error (read src): {msg}")

    # Upload HTML copy to destination
    try:
        s3.put_object(
            Bucket=DEST_BUCKET,
            Key=dest_html_key,
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
            CacheControl="no-cache",
        )
        print(f"[html] uploaded -> s3://{DEST_BUCKET}/{dest_html_key}")
    except ClientError as e:
        msg = e.response.get("Error", {}).get("Message", str(e))
        return _error(500, f"S3 error (write html): {msg}")

    # Render PDF with Playwright / Chromium
    pdf_ok = False
    pdf_err = None
    try:
        _render_pdf_playwright(
            html=html,
            out_bucket=DEST_BUCKET,
            out_key=dest_pdf_key,
            pdf_format=PDF_FORMAT,
            wait_mode=WAIT_MODE,
            timeout_ms=PAGE_TIMEOUT_MS,
        )
        pdf_ok = True
    except Exception as e:
        pdf_err = str(e)
        print(f"[error] PDF generation failed: {pdf_err}")

    # Respond
    if debug:
        return _json({
            "src_bucket": SRC_BUCKET,
            "dest_bucket": DEST_BUCKET,
            "prefix": prefix,
            "html_key": src_key,
            "dest_html_key": dest_html_key,
            "dest_pdf_key": dest_pdf_key,
            "pdf_ok": pdf_ok,
            "pdf_error": pdf_err,
        })

    if not pdf_ok and not ALLOW_PDF_SKIP:
        return _error(500, f"PDF generation failed: {pdf_err}")

    # If not debug: return HTML body (useful to preview in API test)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        "body": html,
    }


# ---------- helpers ----------
def _want_debug(event: dict) -> bool:
    """True if debug=1 passed via queryStringParameters or event JSON"""
    try:
        qs = event.get("queryStringParameters") or {}
        raw = qs.get("debug", None)
        if raw is None:
            raw = event.get("debug", "")
        dv = str(raw).strip().lower()
        return dv in ("1", "true", "yes")
    except Exception:
        return False


def _resolve_month_year(event):
    event = event or {}
    qs = event.get("queryStringParameters") or {}

    def _get(key):
        v = qs.get(key)
        if v is None and isinstance(event, dict):
            v = event.get(key)
        return str(v).strip() if v is not None else None

    month = (_get("month") or "auto").lower()
    year  = _get("year")

    now = datetime.now(timezone.utc)
    if month in ("auto", ""):
        use_dt = now
    elif month in ("prev", "previous", "last"):
        first_of_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        use_dt = first_of_this - timedelta(days=1)
    else:
        if not month.isdigit() or not (1 <= int(month) <= 12):
            raise ValueError('Invalid "month". Use two digits like "09", or "auto", or "prev".')
        y = int(year) if year else now.year
        use_dt = datetime(y, int(month), 1, tzinfo=timezone.utc)

    if not year:
        year = str(use_dt.year)

    month_str = f"{use_dt.month:02d}" if month in ("auto", "prev", "previous", "last", "") else f"{int(month):02d}"
    return month_str, year


def _find_latest_report(bucket, prefix):
    """Return latest object dict whose key is:
       prefix + SRC_FILE_NAME  OR  prefix + */ + SRC_FILE_NAME
    """
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    latest = None
    for page in pages:
        contents = page.get("Contents", []) or []
        if not contents:
            continue
        candidates = []
        for obj in contents:
            key = obj.get("Key", "")
            if key == f"{prefix}{SRC_FILE_NAME}":
                candidates.append(obj)
            elif fnmatch.fnmatch(key, f"{prefix}*/{SRC_FILE_NAME}"):
                candidates.append(obj)
        if candidates:
            candidates.sort(key=lambda o: o["LastModified"], reverse=True)
            pick = candidates[0]
            if (latest is None) or (pick["LastModified"] > latest["LastModified"]):
                latest = pick
    return latest


def _render_pdf_playwright(html: str, out_bucket: str, out_key: str,
                           pdf_format: str = "A4",
                           wait_mode: str = "load",
                           timeout_ms: int = 60000):
    """Render the provided HTML string to PDF using Playwright/Chromium and upload to S3."""
    from playwright.sync_api import sync_playwright

    # Sanitize wait mode
    wait_until = wait_mode if wait_mode in ("load", "domcontentloaded", "networkidle") else "load"

    out_pdf = "/tmp/out.pdf"

    with sync_playwright() as p:
        # Critical flags for Lambda (avoid GPU and /dev/shm issues)
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--mute-audio",
                "--single-process",
            ],
        )
        try:
            page = browser.new_page()
            page.set_default_timeout(timeout_ms)
            # Use screen media and allow CSS colors/backgrounds
            page.emulate_media(media="screen")
            page.set_content(html, wait_until=wait_until)
            page.pdf(
                path=out_pdf,
                format=pdf_format,
                print_background=True,
                prefer_css_page_size=True,
                scale=1.0,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            browser.close()

    # Upload
    with open(out_pdf, "rb") as f:
        s3.put_object(
            Bucket=out_bucket,
            Key=out_key,
            Body=f.read(),
            ContentType="application/pdf",
            CacheControl="no-cache",
        )
    print(f"[pdf] uploaded -> s3://{out_bucket}/{out_key}")


def _json(obj: dict):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(obj),
    }


def _error(code: int, message: str):
    print(f"[error] {message}")
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message}),
    }
