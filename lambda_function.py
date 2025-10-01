import os, json, boto3, pdfkit
from datetime import datetime
from botocore.exceptions import ClientError

# ---- ENV you wanted kept ----
SRC_BUCKET   = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET  = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX  = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT   = os.environ.get("PDF_FORMAT",  "A4")     # A4/Letter
JS_DELAY_MS  = int(os.environ.get("JS_DELAY_MS", "5000"))   # ms for JS to draw charts
WINDOW_STATUS = os.environ.get("WINDOW_STATUS", "")    # e.g. set to "done" if your HTML does window.status='done'
DISABLE_SMART_SHRINKING = os.environ.get("DISABLE_SMART_SHRINKING", "false").lower() == "true"
ORIENTATION = os.environ.get("PDF_ORIENTATION", "Portrait") # Portrait/Landscape

# writable caches in Lambda
os.makedirs("/tmp/.cache/fontconfig", exist_ok=True)
os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")

s3 = boto3.client("s3")

def _ym(event: dict):
    now = datetime.utcnow()
    y = str(event.get("year")  or now.year).zfill(4)
    m = str(event.get("month") or now.month).zfill(2)
    return y, m

def _key(y, m, name): return f"{BASE_PREFIX}/{y}/{m}/{name}"

def _pdf_opts():
    opts = {
        "page-size": PDF_FORMAT,
        "orientation": ORIENTATION,
        "print-media-type": None,
        "enable-local-file-access": None,
        "encoding": "UTF-8",
        "margin-top": "0mm", "margin-right": "0mm",
        "margin-bottom": "0mm", "margin-left": "0mm",
        "dpi": "96",
    }
    if DISABLE_SMART_SHRINKING:
        opts["disable-smart-shrinking"] = None
    if WINDOW_STATUS:
        opts["window-status"] = WINDOW_STATUS
    else:
        opts["javascript-delay"] = str(JS_DELAY_MS)
    return opts

def handler(event, context=None):
    y, m = _ym(event or {})
    html_key = _key(y, m, "uptime-report.html")
    pdf_key  = _key(y, m, "uptime-report.pdf")

    # 1) fetch HTML
    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_key)
        html = obj["Body"].read().decode("utf-8", errors="ignore")
    except ClientError as e:
        return {"statusCode": 404, "headers": {"Content-Type":"application/json"},
                "body": json.dumps({"error": f"Missing {SRC_BUCKET}/{html_key}", "detail": str(e)})}

    # 2) copy HTML to dest (debug-friendly)
    try:
        s3.copy_object(
            CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
            Bucket=DEST_BUCKET, Key=html_key,
            MetadataDirective="REPLACE",
            ContentType="text/html; charset=utf-8"
        )
    except Exception:
        pass

    # 3) render with wkhtmltopdf
    try:
        config = pdfkit.configuration(wkhtmltopdf="/usr/local/bin/wkhtmltopdf")
        pdf_bytes = pdfkit.from_string(html, False, options=_pdf_opts(), configuration=config)
    except Exception as e:
        return {"statusCode": 500, "headers": {"Content-Type":"application/json"},
                "body": json.dumps({"error": f"PDF generation failed: {e.__class__.__name__}: {e}"})}

    # 4) upload PDF
    s3.put_object(Bucket=DEST_BUCKET, Key=pdf_key, Body=pdf_bytes, ContentType="application/pdf")

    return {"statusCode": 200, "headers": {"Content-Type":"application/json"},
            "body": json.dumps({
                "src_bucket": SRC_BUCKET, "dest_bucket": DEST_BUCKET,
                "prefix": f"{BASE_PREFIX}/{y}/{m}/",
                "html_key": html_key, "dest_html_key": html_key, "dest_pdf_key": pdf_key,
                "js_delay_ms": JS_DELAY_MS, "window_status": WINDOW_STATUS or None,
                "smart_shrinking_disabled": DISABLE_SMART_SHRINKING
            })}
