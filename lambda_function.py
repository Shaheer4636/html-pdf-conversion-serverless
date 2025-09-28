import os
import json
import boto3
import datetime as dt
import tempfile
import inspect
import logging

# --- logging ---
log = logging.getLogger()
log.setLevel(logging.INFO)

s3 = boto3.client("s3")

# ====== CONFIG (env overrides) ======
BUCKET_NAME_SRC = os.getenv("SRC_BUCKET", "lambda-output-report-000000987123")
DEST_BUCKET     = os.getenv("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX     = os.getenv("BASE_PREFIX", "uptime")
SRC_FILE_NAME   = "uptime-report.html"
OUT_HTML_NAME   = "uptime-report.html"
OUT_PDF_NAME    = "uptime-report.pdf"
REGION          = os.getenv("AWS_REGION", "us-east-1")
# ====================================

# --- Safe import of WeasyPrint and pydyf ---
try:
    import weasyprint
    from weasyprint import HTML, CSS
except Exception as e:
    log.exception("Failed to import weasyprint")
    raise

try:
    import pydyf
except Exception as e:
    log.exception("Failed to import pydyf")
    raise

def _maybe_shim_pydyf_init():
    """
    WeasyPrint 61.x calls pydyf.PDF with positional args. If the pydyf we got
    has a zero-arg __init__, shim it so calls with args don't explode.
    """
    try:
        sig = inspect.signature(pydyf.PDF.__init__)
        log.info("[versions] weasyprint=%s pydyf=%s", getattr(weasyprint, "__version__", "?"), getattr(pydyf, "__version__", "?"))
        log.info("[versions] PDF.__init__ signature: %s", sig)
        if len(sig.parameters) <= 1:
            # (__init__(self)) -> create a wrapper that swallows args
            _orig = pydyf.PDF.__init__
            def _shim(self, *args, **kwargs):
                return _orig(self)
            pydyf.PDF.__init__ = _shim
            log.warning("[shim] Applied pydyf.PDF.__init__ shim for compatibility")
    except Exception as e:
        log.warning("Could not inspect/patch pydyf.PDF: %s", e)

def _s3_key(prefix, year, month, filename):
    return f"{prefix}/{year}/{month}/{filename}"

def _get_src_html(bucket, key):
    try:
        obj = s3.get_object(Bucket=bucket, Key=key)
        return obj["Body"].read().decode("utf-8")
    except s3.exceptions.NoSuchKey:
        raise FileNotFoundError(f"s3://{bucket}/{key} not found")
    except Exception as e:
        raise

def _put_s3(bucket, key, body, content_type):
    s3.put_object(Bucket=bucket, Key=key, Body=body.encode("utf-8") if isinstance(body, str) else body,
                  ContentType=content_type)

def _ensure_bucket(bucket):
    # HEAD bucket to verify it exists & we have perms
    s3.head_bucket(Bucket=bucket)

def handler(event, context):
    # --- inputs ---
    month = (event or {}).get("month") or f"{dt.date.today().month:02d}"
    year  = (event or {}).get("year")  or f"{dt.date.today().year:04d}"
    debug = (event or {}).get("debug") in (1, True, "1", "true", "yes")

    log.info("[versions] weasyprint=%s pydyf=%s", getattr(weasyprint, "__version__", "?"), getattr(pydyf, "__version__", "?"))
    log.info("[paths] sys.path[0:3]=%s", __import__("sys").path[0:3])

    # --- sanity checks ---
    try:
        _ensure_bucket(DEST_BUCKET)
        log.info("[cfg] dest bucket ok: %s", DEST_BUCKET)
    except Exception as e:
        return _err(500, f"S3 dest bucket check failed for '{DEST_BUCKET}': {e}")

    src_key  = _s3_key(BASE_PREFIX, year, month, SRC_FILE_NAME)
    out_html = _s3_key(BASE_PREFIX, year, month, OUT_HTML_NAME)
    out_pdf  = _s3_key(BASE_PREFIX, year, month, OUT_PDF_NAME)

    log.info("[cfg] SRC_BUCKET='%s' DEST_BUCKET='%s' BASE_PREFIX='%s' REGION='%s'", BUCKET_NAME_SRC, DEST_BUCKET, BASE_PREFIX, REGION)
    log.info("[src] using: s3://%s/%s", BUCKET_NAME_SRC, src_key)

    # --- read HTML from source ---
    try:
        html_string = _get_src_html(BUCKET_NAME_SRC, src_key)
    except FileNotFoundError as e:
        return _err(404, str(e))
    except Exception as e:
        return _err(500, f"Failed to read source HTML: {e}")

    # --- write the HTML into destination too (as you’re doing today) ---
    try:
        _put_s3(DEST_BUCKET, out_html, html_string, "text/html; charset=utf-8")
        log.info("[html] uploaded -> s3://%s/%s", DEST_BUCKET, out_html)
    except Exception as e:
        return _err(500, f"Failed to write HTML to destination: {e}")

    # --- WeasyPrint render ---
    _maybe_shim_pydyf_init()  # critical

    try:
        # Use a small stylesheet to keep page predictable
        css = CSS(string="@page { size: A4; margin: 12mm }")
        with tempfile.NamedTemporaryFile(suffix=".pdf", dir="/tmp", delete=False) as tmp_pdf:
            # Render
            HTML(string=html_string, base_url="/").write_pdf(tmp_pdf.name, stylesheets=[css])
            tmp_pdf_path = tmp_pdf.name

        # Upload PDF
        with open(tmp_pdf_path, "rb") as fh:
            s3.put_object(Bucket=DEST_BUCKET, Key=out_pdf, Body=fh.read(), ContentType="application/pdf")

        log.info("[pdf] uploaded -> s3://%s/%s", DEST_BUCKET, out_pdf)

        body = {
            "ok": True,
            "html_uri": f"s3://{DEST_BUCKET}/{out_html}",
            "pdf_uri":  f"s3://{DEST_BUCKET}/{out_pdf}",
        }
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body),
        }

    except Exception as e:
        log.exception("[error] PDF generation failed")
        return _err(500, f"PDF generation failed: {e}")

def _err(code, msg):
    log.error(msg)
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }

# Lambda entrypoint
def lambda_handler(event, context):
    return handler(event, context)
