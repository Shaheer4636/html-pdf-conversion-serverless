import json, os, sys, io, subprocess, shlex, tempfile, inspect
from datetime import datetime, timezone, timedelta
import boto3
from botocore.exceptions import ClientError

# ====== CONFIG (env overrides) ======
SRC_BUCKET   = os.getenv("SRC_BUCKET",   "lambda-output-report-000000987123")
DEST_BUCKET  = os.getenv("DEST_BUCKET",  "pdf-uptime-reports-0000009")
BASE_PREFIX  = os.getenv("BASE_PREFIX",  "uptime")
SRC_FILE_NAME  = "uptime-report.html"
OUT_HTML_NAME  = "uptime-report.html"
OUT_PDF_NAME   = "uptime-report.pdf"
PDF_FORMAT     = str(os.getenv("PDF_FORMAT", "A4"))  # A4, Letter, etc. via @page CSS
ALLOW_PDF_SKIP = os.getenv("ALLOW_PDF_SKIP", "false").lower() in ("1","true","yes")
# ====================================

s3 = boto3.client("s3")

def lambda_handler(event, context):
    # Make caches writable (fontconfig, etc.)
    os.environ.setdefault("HOME", "/tmp")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp")

    try:
        month_str, year_str = _resolve_month_year(event or {})
    except ValueError as ve:
        return _error(400, str(ve))

    prefix = f"{BASE_PREFIX}/{year_str}/{month_str}/"
    print(f"[cfg] SRC_BUCKET='{SRC_BUCKET}' DEST_BUCKET='{DEST_BUCKET}' BASE_PREFIX='{BASE_PREFIX}'")
    src_key = f"{prefix}{SRC_FILE_NAME}"
    print(f"[src] s3://{SRC_BUCKET}/{src_key}")

    # Validate dest bucket
    try:
        s3.head_bucket(Bucket=DEST_BUCKET)
        print(f"[cfg] dest bucket ok: {DEST_BUCKET}")
    except ClientError as e:
        return _error(404, f"S3 head_bucket failed for '{DEST_BUCKET}': {e.response.get('Error', {}).get('Message', str(e))}")

    # Resolve source key (direct or nested)
    key = _find_existing_key(SRC_BUCKET, prefix, SRC_FILE_NAME)
    if not key:
        return _error(404, f'No "{SRC_FILE_NAME}" under s3://{SRC_BUCKET}/{prefix} (direct or nested).')

    # Read HTML
    try:
        obj = s3.get_object(Bucket=SRC_BUCKET, Key=key)
        html = obj["Body"].read().decode("utf-8", errors="replace")
    except Exception as e:
        return _error(500, f"Failed to read source HTML: {e}")

    # Copy HTML to destination
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

    # Render to PDF via Chromium headless CLI
    try:
        pdf_bytes = _render_pdf_chromium(html, pdf_format=PDF_FORMAT)
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

# ---------- chromium rendering ----------

def _render_pdf_chromium(html: str, pdf_format: str = "A4") -> bytes:
    """
    Uses system Chromium in headless mode to render modern HTML/CSS/JS.
    - Writes HTML to /tmp/in.html
    - Injects @page size to control paper
    - Runs chromium --headless=new --print-to-pdf
    """
    chrome = _which("chromium-browser") or _which("chromium")
    if not chrome:
        raise RuntimeError("Chromium not found on PATH")

    with tempfile.TemporaryDirectory(dir="/tmp") as td:
        in_html = os.path.join(td, "in.html")
        out_pdf = os.path.join(td, "out.pdf")

        # Inject a minimal @page rule so size is honored
        html_with_size = f"""<!doctype html>
<html>
<head><meta charset="utf-8">
<style>@page {{ size: {pdf_format}; margin: 12mm; }}</style>
</head>
<body>{html}</body>
</html>"""

        with open(in_html, "w", encoding="utf-8") as f:
            f.write(html_with_size)

        args = [
            chrome,
            "--headless=new",
            "--disable-gpu",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            "--font-render-hinting=none",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-features=Translate,BackForwardCache,AcceptCHFrame,MediaRouter",
            f"--print-to-pdf={out_pdf}",
            "--print-to-pdf-no-header",
            "--virtual-time-budget=10000",
            "--run-all-compositor-stages-before-draw",
            f"file://{in_html}",
        ]

        print(f"[chromium] exec: {' '.join(shlex.quote(a) for a in args)}")
        proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            raise RuntimeError(f"Chromium CLI failed (exit {proc.returncode}). stderr: {proc.stderr.strip()} stdout: {proc.stdout.strip()}")

        if not os.path.exists(out_pdf) or os.path.getsize(out_pdf) == 0:
            raise RuntimeError("Chromium produced no PDF output")

        with open(out_pdf, "rb") as f:
            return f.read()

def _which(name):
    for p in os.environ.get("PATH", "").split(":"):
        cand = os.path.join(p, name)
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return None

# ---------- helpers ----------

def _resolve_month_year(event):
    qs = (event.get("queryStringParameters") or {}) if isinstance(event, dict) else {}
    def _get(k):
        v = qs.get(k) if isinstance(qs, dict) else None
        if v is None and isinstance(event, dict):
            v = event.get(k)
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
    qs = (event.get("queryStringParameters") or {}) if isinstance(event, dict) else {}
    v = qs.get("debug") if isinstance(qs, dict) else None
    if v is None and isinstance(event, dict):
        v = event.get("debug")
    if isinstance(v, bool): return v
    if isinstance(v, (int, float)): return v != 0
    if isinstance(v, str): return v.strip().lower() in ("1", "true", "yes", "on")
    return False

def _error(code, message):
    print(f"[error] {message}")
    return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": message})}
