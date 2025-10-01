import os, json, boto3, pdfkit
from datetime import datetime
from botocore.exceptions import ClientError

SRC_BUCKET      = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET     = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX     = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT      = os.environ.get("PDF_FORMAT",  "A4")
JS_DELAY_MS     = int(os.environ.get("JS_DELAY_MS", "6000"))
ALLOW_PDF_SKIP  = os.environ.get("ALLOW_PDF_SKIP", "false")
# ------------------

os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")

s3 = boto3.client("s3")

def _yyyymm(event: dict):
    now = datetime.utcnow()
    year  = str(event.get("year")  or now.year).zfill(4)
    month = str(event.get("month") or now.month).zfill(2)
    return year, month

def _key(y, m, name): return f"{BASE_PREFIX}/{y}/{m}/{name}"

def lambda_handler(event, context=None):
    if str(ALLOW_PDF_SKIP).lower() == "true":
        return {"statusCode": 200, "headers":{"Content-Type":"application/json"},
                "body": json.dumps({"skipped": True, "reason": "ALLOW_PDF_SKIP=true"})}

    y, m = _yyyymm(event or {})
    html_key = _key(y, m, "uptime-report.html")
    pdf_key  = _key(y, m, "uptime-report.pdf")

    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_key)
    except ClientError as e:
        return {"statusCode": 404, "headers":{"Content-Type":"application/json"},
                "body": json.dumps({"error": f"Missing {SRC_BUCKET}/{html_key}", "detail": str(e)})}

    html = obj["Body"].read().decode("utf-8", errors="ignore")

    # keep a copy of HTML in destination for inspection
    s3.copy_object(CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
                   Bucket=DEST_BUCKET, Key=html_key,
                   MetadataDirective="REPLACE",
                   ContentType="text/html; charset=utf-8")

    config = pdfkit.configuration(wkhtmltopdf="/usr/local/bin/wkhtmltopdf")
    options = {
        "page-size": PDF_FORMAT,
        "print-media-type": None,
        "enable-local-file-access": None,
        "encoding": "UTF-8",
        "margin-top": "0mm", "margin-right": "0mm",
        "margin-bottom": "0mm", "margin-left": "0mm",
        "javascript-delay": str(JS_DELAY_MS),
        # If your page sets window.status='done' when it’s fully rendered, you can use:
        # "window-status": "done"
    }

    pdf_bytes = pdfkit.from_string(html, False, options=options, configuration=config)

    s3.put_object(Bucket=DEST_BUCKET, Key=pdf_key,
                  Body=pdf_bytes, ContentType="application/pdf")

    return {"statusCode": 200, "headers":{"Content-Type":"application/json"},
            "body": json.dumps({
                "src_bucket": SRC_BUCKET, "dest_bucket": DEST_BUCKET,
                "prefix": f"{BASE_PREFIX}/{y}/{m}/",
                "html_key": html_key, "dest_html_key": html_key, "dest_pdf_key": pdf_key,
                "js_delay_ms": JS_DELAY_MS
            })}
