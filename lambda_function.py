# lambda_function.py
import json, os, sys, io, inspect
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError

# Ensure vendored deps are first
VENDOR_DIR = "/var/task/vendor"
if VENDOR_DIR not in sys.path:
    sys.path.insert(0, VENDOR_DIR)

from weasyprint import HTML, CSS
import weasyprint, pydyf

# ====== CONFIG (env overrides) ======
SRC_BUCKET   = os.getenv("SRC_BUCKET",   "lambda-output-report-000000987123")
DEST_BUCKET  = os.getenv("DEST_BUCKET",  "pdf-uptime-reports-0000009")
BASE_PREFIX  = os.getenv("BASE_PREFIX",  "uptime")
SRC_FILE_NAME  = "uptime-report.html"
OUT_HTML_NAME  = "uptime-report.html"
OUT_PDF_NAME   = "uptime-report.pdf"
PDF_FORMAT     = str(os.getenv("PDF_FORMAT", "A4"))  # ensure string
ALLOW_PDF_SKIP = os.getenv("ALLOW_PDF_SKIP", "false").lower() in ("1","true","yes")
# ====================================

s3 = boto3.client("s3")

def lambda_handler(event, context):
    # Quick diagnostics
    try:
        wv = getattr(weasyprint, "__version__", "?")
        pv = getattr(pydyf, "__version__", "?")
        print(f"[versions] weasyprint={wv} pydyf={pv}")
        print(f"[versions] PDF.__init__ signature: {tuple(inspect.signature(pydyf.PDF.__init__).parameters.keys())}")
        print(f"[sys.path0..4] {sys.path[:5]}")
    except Exception as _e:
        print(f"[versions] introspection failed: {_e}")

    # Resolve month/year robustly
    try:
        month_str, year_str = _resolve_month_year(event or {})
    except ValueError as ve:
        return _error(400, str(ve))

    prefix = f"{BASE_PREFIX}/{year_str}/{month_str}/"
    print(f"[cfg] SRC_BUCKET='{SRC_BUCKET}' DEST_BUCKET='{DEST_BUCKET}' BASE_PREFIX='{BASE_PREFIX}'")
    print(f"[src] s3://{SRC_BUCKET}/{prefix}{SRC_FILE_NAME}")

    # Validate dest bucket
    try:
        s3.head_bucket(Bucket=DEST_BUCKET)
        print(f"[cfg] dest bucket ok: {DEST_BUCKET}")
    except ClientError as e:
        return _error(404, f"S3 head_bucket failed for '{DEST_BUCKET}': {e.response.get('Error', {}).get('Message', str(e))}")

    # Find source HTML
    key = _find_existing_key(SRC_BUCKET, prefix, SRC_FILE_NAME)
    if not key:
        return _error(404, f'No "{SRC_FILE_NAME}" under s3://{SRC_BUCKET}/{prefix} (direct or nested).')

    # Read HTML
    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=key)
        html = obj["Body"].read().decode("utf-8", errors="replace")
    except Exception as e:
        return _error(500, f"Failed to read source HTML: {e}")

    # Copy HTML to dest
    dest_html_key = f"{prefix}{OUT_HTML_NAME}"
    try:
        s3.put_object(
            Bucket=DEST_BUCKET, Key=dest_html_key,
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8", CacheControl="no-cache"
        )
        print(f"[html] uploaded -> s3://{DEST_BUCKET}/{dest_html_key}")
    except Exception as e:
        return _error(500, f"Failed to write HTML to destination: {e}")

    # HTML -> PDF
    try:
        pdf_bytes = _render_pdf_weasy(html, pdf_format=PDF_FORMAT)
        dest_pdf_key = f"{prefix}{OUT_PDF_NAME}"
        s3.put_object(
            Bucket=DEST_BUCKET, Key=dest_pdf_key,
            Body=pdf_bytes, ContentType="application/pdf", CacheControl="no-cache"
        )
        print(f"[pdf] uploaded -> s3://{DEST_BUCKET}/{dest_pdf_key}")
    except Exception as e:
        print("[error] PDF generation failed:", e)
        if not ALLOW_PDF_SKIP:
            return _error(500, f"PDF generation failed: {e}")

    # Response
    if _want_debug(event or {}):
        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "src_bucket": SRC_BUCKET,
                "dest_bucket": DEST_BUCKET,
                "prefix": prefix,
                "html_key": key,
                "dest_html_key": dest_html_key,
                "dest_pdf_key": f"{prefix}{OUT_PDF_NAME}"
            })
        }
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
        "body": html
    }

# ---------- helpers ----------

def _render_pdf_weasy(html: str, pdf_format: str = "A4") -> bytes:
    # Writable caches for fontconfig/Pango on Lambda
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp")
    os.environ.setdefault("HOME", "/tmp")
    css = CSS(string=f"@page {{ size: {pdf_format}; margin: 12mm; }}")
    buf = io.BytesIO()
    HTML(string=html, base_url="/").write_pdf(buf, stylesheets=[css])
    return buf.getvalue()

def _resolve_month_year(event):
    """Accepts month/year as str|int in query params or at top-level JSON."""
    qs = (event.get("queryStringParameters") or {}) if isinstance(event, dict) else {}

    def _get(key):
        v = qs.get(key) if isinstance(qs, dict) else None
        if v is None and isinstance(event, dict):
            v = event.get(key)
        if v is None:
            return ""
        return str(v).strip()

    month_raw = _get("month")
    month = (month_raw or "auto").lower()
    year  = _get("year")

    now = datetime.now(timezone.utc)

    if month in ("auto", ""):
        use_dt = now
    elif month in ("prev", "previous", "last"):
        use_dt = (now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1))
    else:
        if not month.isdigit() or not (1 <= int(month) <= 12):
            raise ValueError('Invalid "month". Use two digits like "09", or "auto", or "prev".')
        y = int(year) if year else now.year
        use_dt = datetime(y, int(month), 1, tzinfo=timezone.utc)

    if not year:
        year = str(use_dt.year)
    return f"{use_dt.month:02d}", year

def _find_existing_key(bucket, prefix, filename):
    direct = f"{prefix}{filename}"
    try:
        s3.head_object(Bucket=bucket, Key=direct)
        return direct
    except ClientError:
        pass
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            k = obj.get("Key", "")
            if k.endswith(f"/{filename}") or k == direct:
                return k
    return None

def _want_debug(event):
    """Accepts debug as bool|int|str at query or top-level."""
    qs = (event.get("queryStringParameters") or {}) if isinstance(event, dict) else {}
    v = qs.get("debug") if isinstance(qs, dict) else None
    if v is None and isinstance(event, dict):
        v = event.get("debug")

    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return False

def _error(code, message):
    print(f"[error] {message}")
    return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": message})}
