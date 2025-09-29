import os, json, tempfile, boto3
from playwright.sync_api import sync_playwright

s3 = boto3.client("s3")

SRC_BUCKET  = os.getenv("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.getenv("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.getenv("BASE_PREFIX", "uptime")
REGION      = os.getenv("AWS_REGION",  os.getenv("REGION", "us-east-1"))

HTML_NAME = "uptime-report.html"
PDF_NAME  = "uptime-report.pdf"

def _prefix(event):
    y = (event.get("year") or "").strip() or "2025"
    m = (event.get("month") or "").strip() or "09"
    return f"{BASE_PREFIX}/{y}/{m}"

def _key(prefix, name): return f"{prefix}/{name}"

def lambda_handler(event, context):
    prefix  = _prefix(event or {})
    html_k  = _key(prefix, HTML_NAME)
    pdf_k   = _key(prefix, PDF_NAME)

    # 1) get HTML from source bucket
    obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_k)
    html = obj["Body"].read().decode("utf-8")

    # 2) also copy HTML to dest (as you were doing)
    s3.put_object(Bucket=DEST_BUCKET, Key=html_k, Body=html.encode("utf-8"),
                  ContentType="text/html; charset=utf-8")

    # 3) render PDF with Chromium via Playwright (faithful to HTML+CSS)
    with tempfile.TemporaryDirectory() as td:
        out_pdf = os.path.join(td, "out.pdf")
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox", "--disable-dev-shm-usage"])
            page = browser.new_page()
            # Increase if your HTML fetches assets via absolute URLs
            page.set_default_timeout(60000)
            page.set_content(html, wait_until="load")
            # print_background=True preserves CSS backgrounds, logos etc.
            page.pdf(path=out_pdf, format="A4", print_background=True, scale=1.0)
            browser.close()

        # 4) upload result
        with open(out_pdf, "rb") as fh:
            s3.put_object(Bucket=DEST_BUCKET, Key=pdf_k, Body=fh.read(),
                          ContentType="application/pdf")

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "src_bucket": SRC_BUCKET, "dest_bucket": DEST_BUCKET,
            "prefix": prefix, "html_key": html_k, "dest_pdf_key": pdf_k
        })
    }
