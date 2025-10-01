import os
import json
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from playwright.sync_api import sync_playwright

# -------- your env vars, kept ----------
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")

# How long to wait for the page to be "ready" before printing
# Options: "load", "domcontentloaded", "networkidle" (best for JS charts)
PLAYWRIGHT_WAIT = os.environ.get("PLAYWRIGHT_WAIT", "networkidle").lower()

# Paper format: A4, Letter, etc.
PDF_FORMAT  = os.environ.get("PDF_FORMAT", "A4")

# JS rendering extra delay (ms) after waitUntil; useful for charts finishing animations
EXTRA_DELAY_MS = int(os.environ.get("EXTRA_DELAY_MS", "0"))

# S3 client
s3 = boto3.client("s3")

def _ym_from_event(event: dict):
    now = datetime.utcnow()
    year  = str(event.get("year")  or now.year).zfill(4)
    month = str(event.get("month") or now.month).zfill(2)
    return year, month

def _key(prefix: str, year: str, month: str, name: str) -> str:
    return f"{prefix}/{year}/{month}/{name}".lstrip("/")

def _s3_read_text(bucket: str, key: str) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", errors="ignore")

def lambda_handler(event, context=None):
    """
    Event formats supported:

    A) { "year": 2025, "month": 9 }
       -> reads:  {BASE_PREFIX}/{year}/{month}/uptime-report.html

    B) { "html_key": "uptime/2025/09/uptime-report.html",
         "pdf_key":  "uptime/2025/09/uptime-report.pdf" }  # pdf_key optional
    """
    try:
        event = event or {}
        year, month = _ym_from_event(event)

        # Allow direct keys via event override
        html_key = event.get("html_key") or _key(BASE_PREFIX, year, month, "uptime-report.html")
        pdf_key  = event.get("pdf_key")  or _key(BASE_PREFIX, year, month, "uptime-report.pdf")

        # 1) Fetch HTML
        try:
            html = _s3_read_text(SRC_BUCKET, html_key)
        except ClientError as e:
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": f"Missing {SRC_BUCKET}/{html_key}", "detail": str(e)})
            }

        # 2) Copy HTML to destination (for inspection)
        try:
            s3.copy_object(
                CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
                Bucket=DEST_BUCKET, Key=html_key,
                MetadataDirective="REPLACE",
                ContentType="text/html; charset=utf-8"
            )
        except ClientError:
            # Non-fatal – continue rendering even if copy fails
            pass

        # 3) Render to PDF (Chromium headless)
        # Build a base URL so relative <link>/<img> in your HTML resolve against S3
        # Example: if html_key = uptime/2025/09/uptime-report.html -> base dir = uptime/2025/09/
        base_dir = html_key.rsplit("/", 1)[0] + "/"
        base_url = f"https://{SRC_BUCKET}.s3.amazonaws.com/{base_dir}"

        wait_until = PLAYWRIGHT_WAIT if PLAYWRIGHT_WAIT in {"load", "domcontentloaded", "networkidle"} else "networkidle"

        with sync_playwright() as p:
            # Headless Chromium that’s already present in the image
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--font-render-hinting=medium",
                ],
            )
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 1920},
                    device_scale_factor=1.0,
                    java_script_enabled=True,
                    base_url=base_url,   # makes relative URLs work
                )
                page = context.new_page()

                # Feed HTML directly so we don’t need a web server
                page.set_content(html, wait_until=wait_until, timeout=120_000)

                if EXTRA_DELAY_MS > 0:
                    page.wait_for_timeout(EXTRA_DELAY_MS)

                # Print to PDF (mimics Ctrl+P)
                pdf_bytes = page.pdf(
                    format=PDF_FORMAT,
                    print_background=True,
                    prefer_css_page_size=True,   # honor @page size from print CSS
                    margin={"top": "0.4in", "right": "0.4in", "bottom": "0.6in", "left": "0.4in"},
                    scale=1.0,
                    display_header_footer=False,
                    timeout=120_000,
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

        # 4) Upload PDF
        s3.put_object(
            Bucket=DEST_BUCKET,
            Key=pdf_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "src_bucket": SRC_BUCKET,
                "dest_bucket": DEST_BUCKET,
                "prefix": f"{BASE_PREFIX}/{year}/{month}/",
                "html_key": html_key,
                "dest_html_key": html_key,
                "dest_pdf_key": pdf_key,
                "wait_until": wait_until,
                "extra_delay_ms": EXTRA_DELAY_MS,
                "format": PDF_FORMAT,
            }),
        }

    except Exception as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"PDF generation failed: {e.__class__.__name__}: {e}"}),
        }
