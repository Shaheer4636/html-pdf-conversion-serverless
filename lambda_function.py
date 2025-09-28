import os, sys, json, logging, tempfile, datetime as dt
import boto3

VENDOR = os.path.join(os.path.dirname(__file__), "vendor")
if VENDOR not in sys.path:
    sys.path.insert(0, VENDOR)

from weasyprint import HTML, CSS
import weasyprint, pydyf

log = logging.getLogger()
log.setLevel(logging.INFO)
s3 = boto3.client("s3")

SRC_BUCKET  = os.getenv("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.getenv("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.getenv("BASE_PREFIX", "uptime")
SRC_FILE    = "uptime-report.html"
OUT_HTML    = "uptime-report.html"
OUT_PDF     = "uptime-report.pdf"

def _s3_key(prefix, year, month, name): return f"{prefix}/{year}/{month}/{name}"

def _err(code, msg):
    log.error(msg)
    return {"statusCode": code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": msg})}

def lambda_handler(event, context):
    log.info("[versions] weasyprint=%s pydyf=%s", getattr(weasyprint,"__version__","?"), getattr(pydyf,"__version__","?"))
    log.info("[files] weasyprint=%s", getattr(weasyprint,"__file__","?"))
    log.info("[files] pydyf=%s", getattr(pydyf,"__file__","?"))
    log.info("[sys.path0..4] %s", sys.path[:5])

    month = (event or {}).get("month") or f"{dt.date.today().month:02d}"
    year  = (event or {}).get("year")  or f"{dt.date.today().year:04d}"

    try:
        s3.head_bucket(Bucket=DEST_BUCKET)
    except Exception as e:
        return _err(500, f"Dest bucket check failed for '{DEST_BUCKET}': {e}")

    src_key  = _s3_key(BASE_PREFIX, year, month, SRC_FILE)
    out_html = _s3_key(BASE_PREFIX, year, month, OUT_HTML)
    out_pdf  = _s3_key(BASE_PREFIX, year, month, OUT_PDF)

    log.info("[cfg] SRC_BUCKET='%s' DEST_BUCKET='%s' BASE_PREFIX='%s'", SRC_BUCKET, DEST_BUCKET, BASE_PREFIX)
    log.info("[src] s3://%s/%s", SRC_BUCKET, src_key)

    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=src_key)
        html = obj["Body"].read().decode("utf-8")
    except s3.exceptions.NoSuchKey:
        return _err(404, f"s3://{SRC_BUCKET}/{src_key} not found")
    except Exception as e:
        return _err(500, f"Failed to read source HTML: {e}")

    try:
        s3.put_object(Bucket=DEST_BUCKET, Key=out_html, Body=html.encode("utf-8"),
                      ContentType="text/html; charset=utf-8")
        log.info("[html] uploaded -> s3://%s/%s", DEST_BUCKET, out_html)
    except Exception as e:
        return _err(500, f"Failed to write HTML to destination: {e}")

    try:
        css = CSS(string="@page { size: A4; margin: 12mm }")
        with tempfile.NamedTemporaryFile(suffix=".pdf", dir="/tmp", delete=False) as tmp:
            HTML(string=html, base_url="/").write_pdf(tmp.name, stylesheets=[css])
            pdf_path = tmp.name
        with open(pdf_path, "rb") as fh:
            s3.put_object(Bucket=DEST_BUCKET, Key=out_pdf, Body=fh.read(),
                          ContentType="application/pdf")
        log.info("[pdf] uploaded -> s3://%s/%s", DEST_BUCKET, out_pdf)
        return {"statusCode": 200, "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"ok": True,
                                    "html_uri": f"s3://{DEST_BUCKET}/{out_html}",
                                    "pdf_uri":  f"s3://{DEST_BUCKET}/{out_pdf}"})}
    except Exception as e:
        log.exception("PDF generation failed")
        return _err(500, f"PDF generation failed: {e}")


#push
