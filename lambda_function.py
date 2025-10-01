import json, os, tempfile, boto3
from datetime import datetime
from playwright.sync_api import sync_playwright

# -------- keep your env vars --------
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.environ.get("PDF_FORMAT",  "A4")
PW_WAIT     = os.environ.get("PLAYWRIGHT_WAIT", "networkidle")

# ensure writable caches for fonts/playwright
os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")

s3 = boto3.client("s3")

def _yyyymm(event):
    year  = str(event.get("year")  or datetime.utcnow().year).zfill(4)
    month = str(event.get("month") or datetime.utcnow().month).zfill(2)
    return year, month

def _key(year, month, name): return f"{BASE_PREFIX}/{year}/{month}/{name}"

def lambda_handler(event, context=None):
    year, month = _yyyymm(event or {})
    html_key = _key(year, month, "uptime-report.html")
    pdf_key  = _key(year, month, "uptime-report.pdf")

    # fetch HTML from src bucket
    obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_key)
    html = obj["Body"].read().decode("utf-8", errors="ignore")

    # copy HTML to dest for inspection
    s3.copy_object(
        CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
        Bucket=DEST_BUCKET, Key=html_key,
        MetadataDirective="REPLACE",
        ContentType="text/html; charset=utf-8"
    )

    with sync_playwright() as p:
        # IMPORTANT: headless=False + "--headless=old" (only one headless mode)
        browser = p.chromium.launch(
            headless=False,
            args=[
                "--headless=old",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-software-rasterizer",
                "--no-zygote",
                "--single-process",
                "--force-color-profile=srgb",
                "--export-tagged-pdf",
            ],
        )
        try:
            page = browser.new_page()
            page.emulate_media(media="print")
            page.set_content(html, wait_until=PW_WAIT)

            pdf_bytes = page.pdf(
                format=PDF_FORMAT,
                print_background=True,
                prefer_css_page_size=True,
                margin={"top":"0","right":"0","bottom":"0","left":"0"},
                scale=1.0,
            )
        finally:
            browser.close()

    with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
        tmp.write(pdf_bytes); tmp.flush()
        s3.upload_file(tmp.name, DEST_BUCKET, pdf_key,
                       ExtraArgs={"ContentType":"application/pdf"})

    return {
        "statusCode": 200,
        "headers": {"Content-Type":"application/json"},
        "body": json.dumps({
            "src_bucket": SRC_BUCKET,
            "dest_bucket": DEST_BUCKET,
            "prefix": f"{BASE_PREFIX}/{year}/{month}/",
            "html_key": html_key,
            "dest_html_key": html_key,
            "dest_pdf_key": pdf_key
        })
    }
