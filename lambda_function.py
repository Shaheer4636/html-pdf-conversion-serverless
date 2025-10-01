import os
import json
import boto3
import pdfkit
from datetime import datetime
from botocore.exceptions import ClientError
from urllib.request import urlopen

# ---------- ENV ----------
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.environ.get("PDF_FORMAT",  "A4")
JS_DELAY_MS = int(os.environ.get("JS_DELAY_MS", "3000"))

# Path we installed in the Dockerfile
WKHTMLTOPDF_BIN = "/usr/local/bin/wkhtmltopdf"

s3 = boto3.client("s3")

def _yyyymm_from_event(event: dict):
    now = datetime.utcnow()
    y = str(event.get("year") or now.year).zfill(4)
    m = str(event.get("month") or now.month).zfill(2)
    return y, m

def _build_key(year, month, name):
    return f"{BASE_PREFIX}/{year}/{month}/{name}"

def _pdf_options():
    return {
        "page-size": PDF_FORMAT,
        "print-media-type": None,
        "enable-local-file-access": None,
        "encoding": "UTF-8",
        "margin-top": "0mm",
        "margin-right": "0mm",
        "margin-bottom": "0mm",
        "margin-left": "0mm",
        "javascript-delay": str(JS_DELAY_MS),
        # If your HTML sets window.status='done' when charts finish:
        # "window-status": "done",
        # "no-stop-slow-scripts": None
    }

def _load_html_from_s3(bucket: str, key: str) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", errors="ignore")

def _load_html_from_url(url: str) -> str:
    with urlopen(url) as r:
        return r.read().decode("utf-8", errors="ignore")

def lambda_handler(event, context):
    """
    Accepted event shapes (pick one):

    1) Inline HTML (quick console test)
       { "html": "<html>...</html>", "dest_key": "uptime/test.pdf", "js_delay_ms": 2000 }

    2) S3 HTML under default prefix
       { "year": 2025, "month": 10 }   # will read uptime/<year>/<month>/uptime-report.html

    3) S3 HTML explicit
       { "html_key": "uptime/2025/10/uptime-report.html", "dest_key": "uptime/2025/10/uptime-report.pdf" }

    4) Remote URL
       { "html_url": "https://example.com/report.html", "dest_key": "uptime/2025/10/report.pdf" }
    """
    try:
        # Allow override of delay per request
        global JS_DELAY_MS
        if "js_delay_ms" in event:
            JS_DELAY_MS = int(event["js_delay_ms"])

        # Figure out source HTML
        html = None
        if "html" in event:
            html = event["html"]
        elif "html_url" in event:
            html = _load_html_from_url(event["html_url"])
        else:
            # S3 path resolution
            if "html_key" in event:
                html_key = event["html_key"]
                src_bucket = event.get("src_bucket", SRC_BUCKET)
            else:
                year, month = _yyyymm_from_event(event or {})
                html_key = _build_key(year, month, "uptime-report.html")
                src_bucket = SRC_BUCKET

            # fetch
            html = _load_html_from_s3(src_bucket, html_key)

        if not html:
            return {
                "statusCode": 400,
                "body": json.dumps({"error": "No HTML provided/resolved"})
            }

        # Destination key
        if "dest_key" in event:
            pdf_key = event["dest_key"]
        else:
            year, month = _yyyymm_from_event(event or {})
            pdf_key = _build_key(year, month, "uptime-report.pdf")

        # Ensure wkhtmltopdf is there
        config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_BIN)

        # Render
        pdf_bytes = pdfkit.from_string(html, False, options=_pdf_options(), configuration=config)

        # Upload
        s3.put_object(
            Bucket=event.get("dest_bucket", DEST_BUCKET),
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
                "pdf_key": pdf_key,
                "pdf_size": len(pdf_bytes),
                "wkhtmltopdf": WKHTMLTOPDF_BIN,
                "js_delay_ms": JS_DELAY_MS
            }),
        }

    except ClientError as e:
        return {
            "statusCode": 404,
            "body": json.dumps({"error": "S3 access failed", "detail": str(e)})
        }
    except Exception as e:
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }
