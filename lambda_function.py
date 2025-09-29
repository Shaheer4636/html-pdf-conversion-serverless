import os
import json
import tempfile
import boto3
from urllib.parse import urlencode
from playwright.sync_api import sync_playwright

S3 = boto3.client("s3")

# Config via env (with defaults)
SRC_BUCKET   = os.environ.get("SRC_BUCKET", "lambda-output-report-000000987123")
DEST_BUCKET  = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX  = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT   = os.environ.get("PDF_FORMAT", "A4")  # or "Letter"

def _key(year, month, name="uptime-report"):
    return f"{BASE_PREFIX}/{year}/{month}/{name}.html"

def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }

def _download_html(bucket, key, dst_path):
    S3.download_file(bucket, key, dst_path)

def _upload_bytes(bucket, key, data, content_type):
    S3.put_object(Bucket=bucket, Key=key, Body=data, ContentType=content_type)

def lambda_handler(event, context):
    # Input: {"year":"2025","month":"09"}; debug optional
    year  = str((event or {}).get("year", "")).strip() or "2025"
    month = str((event or {}).get("month", "")).strip() or "09"

    html_key = _key(year, month, "uptime-report")
    dest_html_key = html_key
    dest_pdf_key  = html_key.replace(".html", ".pdf")

    # Prep temp files
    os.makedirs("/tmp/fontcache", exist_ok=True)
    html_path = os.path.join(tempfile.gettempdir(), "report.html")

    try:
        # Download HTML from source
        _download_html(SRC_BUCKET, html_key, html_path)

        # Also copy HTML to dest bucket for reference (optional)
        with open(html_path, "rb") as f:
            _upload_bytes(DEST_BUCKET, dest_html_key, f.read(), "text/html")

        # Launch Chromium and print to PDF
        with sync_playwright() as p:
            # Headless Chromium with safe flags for Lambda
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                    "--disable-setuid-sandbox",
                    "--font-render-hinting=none",
                    "--force-color-profile=srgb",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1280, "height": 800},
                color_scheme="light",
                java_script_enabled=True,
                device_scale_factor=1.0,
            )
            page = context.new_page()

            # Load local file so relative assets inside HTML (if any) resolve
            # If your HTML pulls remote assets (fonts/CSS), ensure Lambda has internet egress.
            page.goto(f"file://{html_path}", wait_until="networkidle")

            # Respect CSS @page size when present; else fallback to env format
            pdf = page.pdf(
                format=PDF_FORMAT,
                print_background=True,
                prefer_css_page_size=True,
                margin={"top": "10mm", "right": "10mm", "bottom": "10mm", "left": "10mm"},
                landscape=False,
            )

            context.close()
            browser.close()

        # Upload PDF
        _upload_bytes(DEST_BUCKET, dest_pdf_key, pdf, "application/pdf")

        return _resp(200, {
            "src_bucket": SRC_BUCKET,
            "dest_bucket": DEST_BUCKET,
            "prefix": f"{BASE_PREFIX}/{year}/{month}/",
            "html_key": html_key,
            "dest_html_key": dest_html_key,
            "dest_pdf_key": dest_pdf_key
        })

    except Exception as e:
        return _resp(500, {"error": f"PDF generation failed: {e}"})
