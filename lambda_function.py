import os, json, boto3, pdfkit
from datetime import datetime
from botocore.exceptions import ClientError

# ------------ ENV -------------
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.environ.get("PDF_FORMAT",  "A4")  # A4, Letter, etc.
JS_DELAY_MS = int(os.environ.get("JS_DELAY_MS", "4000"))  # time for JS charts to draw
# --------------------------------

# Lambda container: caches/fonts to /tmp
os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")

s3 = boto3.client("s3")

def _ym(event):
    now = datetime.utcnow()
    year = str((event or {}).get("year") or now.year).zfill(4)
    month = str((event or {}).get("month") or now.month).zfill(2)
    return year, month

def _key(year, month, name): 
    return f"{BASE_PREFIX}/{year}/{month}/{name}"

def lambda_handler(event, context=None):
    year, month = _ym(event)
    html_key = _key(year, month, "uptime-report.html")
    pdf_key  = _key(year, month, "uptime-report.pdf")

    # 1) fetch HTML from source bucket
    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_key)
    except ClientError as e:
        return {
            "statusCode": 404,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"Missing {SRC_BUCKET}/{html_key}", "detail": str(e)})
        }

    html = obj["Body"].read().decode("utf-8", errors="ignore")

    # 2) copy HTML to dest for inspection
    s3.copy_object(
        CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
        Bucket=DEST_BUCKET, Key=html_key,
        MetadataDirective="REPLACE",
        ContentType="text/html; charset=utf-8"
    )

    # 3) render to PDF with wkhtmltopdf via pdfkit
    cfg = pdfkit.configuration(wkhtmltopdf="/usr/local/bin/wkhtmltopdf")
    options = {
        "page-size": PDF_FORMAT,
        "print-media-type": None,
        "enable-local-file-access": None,
        "encoding": "UTF-8",
        "margin-top": "0mm",
        "margin-right": "0mm",
        "margin-bottom": "0mm",
        "margin-left": "0mm",
        # let JS draw charts/canvas
        "javascript-delay": str(JS_DELAY_MS),
        # if your page sets window.status='done' when finished, you can use:
        # "window-status": "done",
        # "no-stop-slow-scripts": None,
        # "load-error-handling": "ignore",
    }

    pdf_bytes = pdfkit.from_string(html, False, options=options, configuration=cfg)

    # 4) upload PDF
    s3.put_object(
        Bucket=DEST_BUCKET,
        Key=pdf_key,
        Body=pdf_bytes,
        ContentType="application/pdf",
    )

    return {
        "statusCode": 200,
        "headers": {"Content-Type":"application/json"},
        "body": json.dumps({
            "src_bucket": SRC_BUCKET,
            "dest_bucket": DEST_BUCKET,
            "prefix": f"{BASE_PREFIX}/{year}/{month}/",
            "html_key": html_key,
            "dest_html_key": html_key,
            "dest_pdf_key": pdf_key,
            "js_delay_ms": JS_DELAY_MS
        })
    }
