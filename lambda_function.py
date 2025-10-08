import os, json, boto3, pdfkit
from datetime import datetime
from botocore.exceptions import ClientError

# ---- Env (kept same keys you already use) ----
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.environ.get("PDF_FORMAT",  "A4")
JS_DELAY_MS = int(os.environ.get("JS_DELAY_MS", "5000"))  # give JS time to paint
WKHTMLTOPDF_BIN = os.environ.get("WKHTMLTOPDF_BIN", "/usr/bin/wkhtmltopdf")  # from Ubuntu package


os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")

s3 = boto3.client("s3")

def _ym(event: dict):
    now = datetime.utcnow()
    y = str(event.get("year")  or now.year).zfill(4)
    m = str(event.get("month") or now.month).zfill(2)
    return y, m

def _key(y, m, name): 
    return f"{BASE_PREFIX}/{y}/{m}/{name}".lstrip("/")

def lambda_handler(event, context=None):
    event = event or {}
    year, month = _ym(event)

    html_key = event.get("html_key") or _key(year, month, "uptime-report.html")
    pdf_key  = event.get("pdf_key")  or _key(year, month, "uptime-report.pdf")

    # 1) fetch HTML
    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_key)
        html = obj["Body"].read().decode("utf-8", errors="ignore")
    except ClientError as e:
        return {
            "statusCode": 404,
            "headers": {"Content-Type":"application/json"},
            "body": json.dumps({"error": f"Missing {SRC_BUCKET}/{html_key}", "detail": str(e)})
        }

    # 2) copy HTML to dest for debugging (non-fatal if it fails)
    try:
        s3.copy_object(
            CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
            Bucket=DEST_BUCKET, Key=html_key,
            MetadataDirective="REPLACE",
            ContentType="text/html; charset=utf-8"
        )
    except ClientError:
        pass

    # 3) render to PDF with wkhtmltopdf
    config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_BIN)
    options = {
        "page-size": PDF_FORMAT,
        "print-media-type": None,
        "enable-local-file-access": None,
        "encoding": "UTF-8",
        "margin-top": "0mm",
        "margin-right": "0mm",
        "margin-bottom": "0mm",
        "margin-left": "0mm",
        # JS render time (increase if charts still blank)
        "javascript-delay": str(JS_DELAY_MS),
        # Helpful if your page uses heavy JS:
        # "no-stop-slow-scripts": None,
        # If your HTML sets window.status='done' when finished:
        # "window-status": "done",
        # "debug-javascript": None,
        # "log-level": "warn",
    }

    try:
        pdf_bytes = pdfkit.from_string(html, False, options=options, configuration=config)
    except OSError as e:
        # Common cause: missing wkhtmltopdf or bad path
        return {
            "statusCode": 500,
            "headers": {"Content-Type":"application/json"},
            "body": json.dumps({"error": f"wkhtmltopdf error: {e}"})
        }

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
            "js_delay_ms": JS_DELAY_MS,
            "format": PDF_FORMAT
        })
    }
