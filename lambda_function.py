import os, json, boto3, pdfkit
from datetime import datetime
from botocore.exceptions import ClientError

# ===== Hard-coded identifiers (edit these three lines to your actual values) =====
LAMBDA_ARN     = "arn:aws:lambda:us-east-1:492046385895:function:uptime-report-pdf"
SRC_BUCKET     = "lambda1-output-009"
DEST_BUCKET    = "pdf-uptime-reports-00000009"
# =================================================================================

BASE_PREFIX      = "uptime"
PDF_FORMAT       = "A4"
JS_DELAY_MS      = 5000                      # ms to let JS render
WKHTMLTOPDF_BIN  = "/usr/bin/wkhtmltopdf"    # wkhtmltopdf path in your layer/image

# Lambda tmp-friendly defaults
os.environ.setdefault("HOME", "/tmp")
os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")

s3 = boto3.client("s3")
sts = boto3.client("sts")

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

    # Diagnostics in CloudWatch logs
    runtime_arn = getattr(context, "invoked_function_arn", "<no-context>")
    try:
        ident = sts.get_caller_identity()
        print("CALLER_STS:", json.dumps(ident))
    except Exception as _e:
        print("CALLER_STS: <failed>", str(_e))
    print(f"HARDCODED_LAMBDA_ARN={LAMBDA_ARN}")
    print(f"RUNTIME_LAMBDA_ARN={runtime_arn}")
    print(f"Read HTML  : s3://{SRC_BUCKET}/{html_key}")
    print(f"Write PDF  : s3://{DEST_BUCKET}/{pdf_key}")

    # 1) fetch HTML
    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=html_key)
        html = obj["Body"].read().decode("utf-8", errors="ignore")
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        status = 403 if code in ("AccessDenied", "403", "Unauthorized") else 404
        return {
            "statusCode": status,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": f"S3 {code} for {SRC_BUCKET}/{html_key}",
                "detail": str(e),
                "lambda_arn_hardcoded": LAMBDA_ARN,
                "lambda_arn_runtime": runtime_arn
            })
        }

    # 2) copy HTML to dest for debugging (best-effort)
    try:
        s3.copy_object(
            CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
            Bucket=DEST_BUCKET,
            Key=html_key,
            MetadataDirective="REPLACE",
            ContentType="text/html; charset=utf-8"
        )
    except ClientError as e:
        print("copy_object failed (non-fatal):", str(e))

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
        "javascript-delay": str(JS_DELAY_MS),
        # "window-status": "done",
        # "no-stop-slow-scripts": None,
        # "debug-javascript": None,
        # "log-level": "warn",
    }

    try:
        pdf_bytes = pdfkit.from_string(html, False, options=options, configuration=config)
    except OSError as e:
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"wkhtmltopdf error: {e}"})
        }

    # 4) upload PDF
    try:
        s3.put_object(
            Bucket=DEST_BUCKET,
            Key=pdf_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        return {
            "statusCode": 403 if code in ("AccessDenied", "403", "Unauthorized") else 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "error": f"S3 {code} on put {DEST_BUCKET}/{pdf_key}",
                "detail": str(e),
                "lambda_arn_hardcoded": LAMBDA_ARN,
                "lambda_arn_runtime": runtime_arn
            })
        }

    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "lambda_arn": LAMBDA_ARN,
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
