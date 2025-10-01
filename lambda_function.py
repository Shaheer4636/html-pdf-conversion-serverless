import os, json, boto3, pdfkit
from datetime import datetime
from botocore.exceptions import ClientError
from urllib.request import urlopen

SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.environ.get("PDF_FORMAT",  "A4")
JS_DELAY_MS = int(os.environ.get("JS_DELAY_MS", "3000"))

WKHTMLTOPDF_BIN = "/usr/local/bin/wkhtmltopdf"
s3 = boto3.client("s3")

def _yyyymm(event: dict):
    now = datetime.utcnow()
    return str(event.get("year") or now.year).zfill(4), str(event.get("month") or now.month).zfill(2)

def _key(y, m, name): return f"{BASE_PREFIX}/{y}/{m}/{name}"

def _options():
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
        # "window-status": "done",
    }

def _html_from_s3(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", errors="ignore")

def lambda_handler(event, context):
    try:
        if "js_delay_ms" in event:
            globals()["JS_DELAY_MS"] = int(event["js_delay_ms"])

        if "html" in event:
            html = event["html"]
        elif "html_url" in event:
            with urlopen(event["html_url"]) as r:
                html = r.read().decode("utf-8", errors="ignore")
        else:
            if "html_key" in event:
                html_key = event["html_key"]
                src_bucket = event.get("src_bucket", SRC_BUCKET)
            else:
                y, m = _yyyymm(event or {})
                html_key = _key(y, m, "uptime-report.html")
                src_bucket = SRC_BUCKET
            html = _html_from_s3(src_bucket, html_key)

        if not html:
            return {"statusCode": 400, "body": json.dumps({"error":"No HTML provided/resolved"})}

        if "dest_key" in event:
            pdf_key = event["dest_key"]
        else:
            y, m = _yyyymm(event or {})
            pdf_key = _key(y, m, "uptime-report.pdf")

        config = pdfkit.configuration(wkhtmltopdf=WKHTMLTOPDF_BIN)
        pdf_bytes = pdfkit.from_string(html, False, options=_options(), configuration=config)

        s3.put_object(
            Bucket=event.get("dest_bucket", DEST_BUCKET),
            Key=pdf_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type":"application/json"},
            "body": json.dumps({
                "dest_bucket": event.get("dest_bucket", DEST_BUCKET),
                "pdf_key": pdf_key,
                "pdf_size": len(pdf_bytes),
            })
        }

    except ClientError as e:
        return {"statusCode": 404, "body": json.dumps({"error":"S3 access failed","detail":str(e)})}
    except Exception as e:
        return {"statusCode": 500, "body": json.dumps({"error":str(e)})}
