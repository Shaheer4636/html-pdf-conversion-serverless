import os
import json
import tempfile
from urllib.parse import quote
import boto3
from playwright.sync_api import sync_playwright

S3 = boto3.client("s3")

# Environment-driven config (set these on the Lambda)
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.environ.get("PDF_FORMAT",  "A4")  # or "Letter"

def _key(year: str, month: str, name="uptime-report", ext="html"):
    return f"{BASE_PREFIX}/{year}/{month}/{name}.{ext}"

def _resp(code, body):
    return {"statusCode": code,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body)}

def lambda_handler(event, context):
    # Expect: {"year":"2025","month":"09"}
    year  = str((event or {}).get("year", "")).strip() or "2025"
    month = str((event or {}).get("month", "")).strip() or "09"

    html_key      = _key(year, month, "uptime-report", "html")
    dest_html_key = html_key
    dest_pdf_key  = _key(year, month, "uptime-report", "pdf")

    # temp file for HTML
    os.makedirs("/tmp", exist_ok=True)
    html_path = os.path.join(tempfile.gettempdir(), "report.html")

    try:
        # 1) Download source HTML
        S3.download_file(SRC_BUCKET, html_key, html_path)

        # 2) Optionally mirror the HTML to destination bucket
        with open(html_path, "rb") as f:
            S3.put_object(Bucket=DEST_BUCKET, Key=dest_html_key, Body=f.read(), ContentType="text/html")

        # 3) Render to PDF using Chromium (Ctrl+P fidelity)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-setuid-sandbox",
                    "--force-color-profile=srgb",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1366, "height": 768},
                device_scale_factor=1.0,
                color_scheme="light",
                java_script_enabled=True,
                accept_downloads=False,
            )
            page = context.new_page()

            # Emulate print CSS like the browser print dialog
            page.emulate_media(media="print")

            # Load local file; relative assets in the HTML will resolve if they’re relative paths
            page.goto(f"file://{html_path}", wait_until="networkidle")

            # Native print-to-PDF (matches Chrome “Save as PDF”)
            pdf_bytes = page.pdf(
                print_background=True,
                prefer_css_page_size=True,  # use @page size if present
                format=PDF_FORMAT,          # fallback if @page not set
                margin={"top": "0mm", "right": "0mm", "bottom": "0mm", "left": "0mm"},
                landscape=False,
            )

            context.close()
            browser.close()

        # 4) Upload PDF
        S3.put_object(Bucket=DEST_BUCKET, Key=dest_pdf_key, Body=pdf_bytes, ContentType="application/pdf")

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
