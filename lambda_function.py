import os
import io
import json
import sys
import boto3
from datetime import datetime
from playwright.sync_api import sync_playwright

# ---------- Runtime environment defaults ----------
# S3 locations
SRC_BUCKET   = os.environ.get("SRC_BUCKET",   "lambda-output-report-000000987123")
DEST_BUCKET  = os.environ.get("DEST_BUCKET",  "pdf-uptime-reports-0000009")
BASE_PREFIX  = os.environ.get("BASE_PREFIX",  "uptime")

# Rendering behavior
ALLOW_NET          = (os.environ.get("ALLOW_NET", "true").lower() == "true")
PLAYWRIGHT_WAIT    = os.environ.get("PLAYWRIGHT_WAIT", "networkidle")  # or 'domcontentloaded'
PAGE_TIMEOUT_MS    = int(os.environ.get("PAGE_TIMEOUT_MS", "25000"))   # 25s
PDF_FORMAT         = os.environ.get("PDF_FORMAT", "A4")

# Pin where Playwright looks for browsers (matches Dockerfile)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

# Helpful in noisy envs
def log(*a):
    print(*a, flush=True)

s3 = boto3.client("s3")


def _build_keys(event: dict):
    """
    Decide month/year and compose S3 keys (HTML src & PDF dest).
    Expects the HTML at:  s3://SRC_BUCKET/BASE_PREFIX/YYYY/MM/uptime-report.html
    """
    year  = str(event.get("year") or datetime.utcnow().year)
    month = str(event.get("month") or f"{datetime.utcnow().month:02d}")
    prefix = f"{BASE_PREFIX}/{year}/{month}/"

    html_key = prefix + "uptime-report.html"
    dest_pdf_key = prefix + "uptime-report.pdf"
    dest_html_key = html_key  # we re-upload html for traceability

    return prefix, html_key, dest_pdf_key, dest_html_key


def _download_html(bucket: str, key: str) -> str:
    log("[s3] get:", f"s3://{bucket}/{key}")
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", "replace")


def _upload_bytes(bucket: str, key: str, data: bytes, content_type: str):
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)
    log(f"[s3] put: s3://{bucket}/{key} ({content_type}, {len(data)} bytes)")


def _render_pdf_with_playwright(html: str) -> bytes:
    # Launch Chromium in Lambda-friendly headless mode
    # (disable GPU, sandbox, and dev-shm issues)
    args = [
        "--headless=new",
        "--no-sandbox",
        "--disable-gpu",
        "--disable-dev-shm-usage",
        "--disable-setuid-sandbox",
        "--disable-features=Translate,BackForwardCache",
        "--export-tagged-pdf",
        "--disable-breakpad",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-ipc-flooding-protection",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        try:
            context = browser.new_context(
                java_script_enabled=True,
                bypass_csp=True,
                accept_downloads=False,
                viewport={"width": 1280, "height": 1800},
                device_scale_factor=2,  # crisp text
            )

            if not ALLOW_NET:
                # Block external network requests. S3-loaded assets still work if inlined.
                def _route(route):
                    if route.request.resource_type in ("document", "stylesheet", "image", "font", "script", "xhr", "fetch"):
                        url = route.request.url
                        # Allow data: and blob:; block http(s) to outside
                        if url.startswith("http://") or url.startswith("https://"):
                            return route.abort()
                    return route.continue_()
                context.route("**/*", _route)

            page = context.new_page()
            page.set_default_navigation_timeout(PAGE_TIMEOUT_MS)
            page.set_default_timeout(PAGE_TIMEOUT_MS)

            # Feed HTML directly; wait for network so fonts/css arrive (if ALLOW_NET)
            page.set_content(html, wait_until=PLAYWRIGHT_WAIT)

            # Produce PDF
            pdf_bytes = page.pdf(
                format=PDF_FORMAT,
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "10mm", "right": "10mm", "bottom": "12mm", "left": "10mm"},
                scale=1.0,  # keep CSS scale
            )
            return pdf_bytes
        finally:
            browser.close()


def lambda_handler(event, context=None):
    try:
        prefix, html_key, dest_pdf_key, dest_html_key = _build_keys(event or {})
        log("[cfg]", f"SRC_BUCKET={SRC_BUCKET} DEST_BUCKET={DEST_BUCKET} BASE_PREFIX={BASE_PREFIX}")
        log("[cfg]", f"WAIT={PLAYWRIGHT_WAIT} ALLOW_NET={ALLOW_NET} TIMEOUT_MS={PAGE_TIMEOUT_MS} FORMAT={PDF_FORMAT}")

        # 1) Pull HTML from S3
        html = _download_html(SRC_BUCKET, html_key)

        # 2) Upload the HTML we actually used (traceability)
        _upload_bytes(DEST_BUCKET, dest_html_key, html.encode("utf-8"), "text/html; charset=utf-8")

        # 3) Render to PDF (Chromium)
        pdf_bytes = _render_pdf_with_playwright(html)

        # 4) Upload PDF
        _upload_bytes(DEST_BUCKET, dest_pdf_key, pdf_bytes, "application/pdf")

        # 5) Return a small OK payload
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "src_bucket": SRC_BUCKET,
                "dest_bucket": DEST_BUCKET,
                "prefix": prefix,
                "html_key": html_key,
                "dest_html_key": dest_html_key,
                "dest_pdf_key": dest_pdf_key
            }),
        }
    except Exception as e:
        log("[error] PDF generation failed:", repr(e))
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"PDF generation failed: {e}"}),
        }
