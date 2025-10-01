import os, json, boto3, pdfkit
from datetime import datetime
from botocore.exceptions import ClientError

# --- ENV (kept your names) ---
SRC_BUCKET   = os.environ.get("SRC_BUCKET", "")
DEST_BUCKET  = os.environ.get("DEST_BUCKET", "")
BASE_PREFIX  = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT   = os.environ.get("PDF_FORMAT", "A4")
ALLOW_PDF_SKIP = os.environ.get("ALLOW_PDF_SKIP", "false").lower() == "true"

# JS wait (milliseconds) for charts/canvas; tweak via env if needed
JS_DELAY_MS  = int(os.environ.get("JS_DELAY_MS", "4000"))

# Paths for wkhtmltopdf (rpm places it under /usr/local/bin)
WKHTMLTOPDF_BIN = os.environ.get("WKHTMLTOPDF_BIN", "/usr/local/bin/wkhtmltopdf")

# Lambda temp-friendly caches
os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")

s3 = boto3.client("s3")

def _yyyymm(event: dict):
    now = datetime.utcnow()
    y = str(event.get("year") or now.year).zfill(4)
    m = str(event.get("month") or now.month).zfill(2)
    return y, m

def _key(year, month, name): 
    return f"{BASE_PREFIX}/{year}/{month}/{name}"

def lambda_handler(event, context=None):
    # Allow dry-run/skip if caller set ALLOW_PDF_SKIP=true and says skip
    if ALLOW_PDF_SKIP and (isinstance(event, dict) and str(event.get("skip", "")).lower() in ("1","true","yes")):
        year, month = _yyyymm(event or {})
        prefix = f"{BASE_PREFIX}/{year}/{month}/"
        return {"statusCode": 200, "headers":{"Content-Type":"application/json"},
                "body": json.dumps({"message":"Skipped by request", "prefix": prefix})}

    year, month = _yyyymm(event or {})
    html_key = _key(year, month, "uptime-report.html")
    pdf_key  = _key(year, month, "uptime-report.pdf")

    if not SRC_BUCKET or not DEST_BUCKET:
        return {"statusCode": 500, "headers":{"Content-Type":"application/json"},
                "body": json.dumps({"error":"SRC_BUCKET/DEST_BUCKET not configured"})}

    # 1) Fetch HTML
    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_key)
        html = obj["Body"].read().decode("utf-8", errors="ignore")
    except ClientError as e:
        return {"statusCode": 404, "headers":{"Content-Type":"application/json"},
                "body": json.dumps({"error": f"Missing {SRC_BUCKET}/{html_key}", "detail": str(e)})}

    # 2) Also copy HTML to DEST for inspection (like your previous flow)
    try:
        s3.copy_object(
            CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
            Bucket=DEST_BUCKET, Key=html_key,
            MetadataDirective="REPLACE",
            ContentType="text/html; charset=utf-8"
        )
    except ClientError:
        # non-fatal
        pass

    # 3) Render to PDF (wkhtmltopdf via pdfkit)
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
        "javascript-delay": str(JS_DELAY_MS),
        # Useful if heavy scripts:
        # "no-stop-slow-scripts": None,
        # Ignore resource load errors instead of failing:
        "load-error-handling": "ignore",
        "load-media-error-handling": "ignore",
        # Keep layout crisp (Chrome-like):
        "dpi": "96",
        "zoom": "1.0",
    }

    try:
        pdf_bytes = pdfkit.from_string(html, False, options=options, configuration=config)
    except Exception as e:
        return {"statusCode": 500, "headers":{"Content-Type":"application/json"},
                "body": json.dumps({"error": f"PDF generation failed: {e.__class__.__name__}: {str(e)}"})}

    # 4) Upload PDF
    try:
        s3.put_object(
            Bucket=DEST_BUCKET,
            Key=pdf_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
    except ClientError as e:
        return {"statusCode": 500, "headers":{"Content-Type":"application/json"},
                "body": json.dumps({"error": f"Upload failed: {str(e)}"})}

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
