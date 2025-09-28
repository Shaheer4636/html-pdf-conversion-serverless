# lambda_function.py
import json
import fnmatch
import os
import re
import urllib.parse
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

# ====== CONFIG (env overrides) ======
BUCKET_NAME_SRC = os.getenv("SRC_BUCKET", "lambda-output-report-000000987123")   # source bucket (HTML lives here)
DEST_BUCKET     = os.getenv("DEST_BUCKET", "pdf-uptime-reports-0000009999")         
BASE_PREFIX     = os.getenv("BASE_PREFIX", "uptime")
SRC_FILE_NAME   = os.getenv("SRC_FILE_NAME", "uptime-report.html")
OUT_HTML_NAME   = os.getenv("OUT_HTML_NAME", "uptime-report.html")
OUT_PDF_NAME    = os.getenv("OUT_PDF_NAME", "uptime-report.pdf")

# Behavior toggles
ALLOW_PDF_SKIP  = os.getenv("ALLOW_PDF_SKIP", "false").lower() in ("1","true","yes")
DEBUG_DEFAULT   = os.getenv("DEBUG_DEFAULT", "false").lower() in ("1","true","yes")
PLAYWRIGHT_WAIT = os.getenv("PLAYWRIGHT_WAIT", "domcontentloaded")  # 'load' | 'domcontentloaded' | 'networkidle'
PDF_FORMAT      = os.getenv("PDF_FORMAT", "A4")                      # e.g. 'A4', 'Letter'
# ====================================

s3 = boto3.client("s3")


def lambda_handler(event, context):  # AWS console default
    return handler(event, context)


def handler(event, context):
    """
    Supports:
      - API GW/ALB:   ?month=09&year=2025[&debug=1] or body {"month":"09","year":"2025","debug":1}
      - S3 event:     ObjectCreated for any key; if it points to uptime/.../uptime-report.html we use that exact key
      - 'month': auto|prev|<01-12>, 'year': optional (defaults to now.year)

    Flow:
      1) Get HTML from source (from S3 event key if present; else latest under uptime/<year>/<month>/**/uptime-report.html).
      2) Upload HTML copy to s3://DEST_BUCKET/uptime/<year>/<month>/uptime-report.html
      3) Render PDF via Playwright Chromium (if available) and upload to .../uptime-report.pdf
      4) Return HTML (if HTTP invocation) or JSON status.
    """
    _log("event", event)

    debug = _get_debug(event)
    try:
        # Prefer S3 event’s exact key if present
        s3_evt = _try_parse_s3_event(event)
        if s3_evt:
            src_bucket, src_key = s3_evt["bucket"], s3_evt["key"]
            if src_bucket != BUCKET_NAME_SRC:
                _log("info", f"S3 event bucket {src_bucket} != configured SRC {BUCKET_NAME_SRC}; using event bucket.")
            month_str, year_str = _extract_year_month_from_key(src_key) or _resolve_month_year(event)
            html = _get_html(src_bucket, src_key)
            _log("info", f"Using S3 event object: s3://{src_bucket}/{src_key}")
        else:
            # Resolve month/year and locate latest HTML
            month_str, year_str = _resolve_month_year(event)
            prefix = f"{BASE_PREFIX}/{year_str}/{month_str}/"
            latest = _find_latest_report(BUCKET_NAME_SRC, prefix)
            if latest is None:
                return _error(404, f'No "{SRC_FILE_NAME}" found under s3://{BUCKET_NAME_SRC}/{prefix} (including subfolders).')
            src_key = latest["Key"]
            html = _get_html(BUCKET_NAME_SRC, src_key)
            _log("info", f"Using latest object: s3://{BUCKET_NAME_SRC}/{src_key}")

        # 2) Save HTML copy to destination
        _upload_html_copy(html, year_str, month_str)

        # 3) Render & upload PDF
        pdf_ok, pdf_err = _render_and_upload_pdf_playwright(html, year_str, month_str)
        if not pdf_ok and not ALLOW_PDF_SKIP:
            return _error(500, f"PDF generation failed: {pdf_err}")

        # 4) Response
        status = {
            "month": month_str,
            "year": year_str,
            "src_bucket": s3_evt["bucket"] if s3_evt else BUCKET_NAME_SRC,
            "src_key": src_key,
            "dest_bucket": DEST_BUCKET,
            "dest_html_key": f"{BASE_PREFIX}/{year_str}/{month_str}/{OUT_HTML_NAME}",
            "dest_pdf_key": f"{BASE_PREFIX}/{year_str}/{month_str}/{OUT_PDF_NAME}",
            "pdf_uploaded": pdf_ok,
            "pdf_error": pdf_err if not pdf_ok else None
        }

        if debug or _is_http(event) is False:
            return {
                "statusCode": 200,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps(status)
            }

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"},
            "body": html
        }

    except ClientError as e:
        msg = e.response.get("Error", {}).get("Message", str(e))
        _log("error", f"S3 error: {msg}")
        return _error(500, f"S3 error: {msg}")
    except Exception as e:
        _log("error", f"Unhandled: {repr(e)}")
        return _error(500, f"Unhandled error: {str(e)}")


# ---------- helpers ----------

def _is_http(event):
    """Rudimentary check if this is API Gateway/ALB style invocation."""
    if not isinstance(event, dict):
        return False
    return "queryStringParameters" in event or "rawPath" in event or "httpMethod" in event


def _get_debug(event):
    if not isinstance(event, dict):
        return DEBUG_DEFAULT
    qs = event.get("queryStringParameters") or {}
    raw = qs.get("debug", event.get("debug", ""))
    try:
        val = str(raw).strip().lower()
    except Exception:
        val = ""
    return (val in ("1", "true", "yes")) or DEBUG_DEFAULT


def _resolve_month_year(event):
    event = event or {}
    qs = event.get("queryStringParameters") or {}

    def _get(key):
        v = qs.get(key)
        if v is None and isinstance(event, dict):
            v = event.get(key)
        if isinstance(v, (int, float)):
            return str(v)
        return (v or "").strip() if isinstance(v, str) else v

    month = (_get("month") or "auto").lower()
    year  = _get("year")

    now = datetime.now(timezone.utc)
    if month in ("auto", ""):
        use_dt = now
    elif month in ("prev", "previous", "last"):
        first_of_this = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        use_dt = first_of_this - timedelta(days=1)
    else:
        if not month.isdigit() or not (1 <= int(month) <= 12):
            raise ValueError('Invalid "month". Use two digits like "09", or "auto", or "prev".')
        y = int(year) if year else now.year
        use_dt = datetime(y, int(month), 1, tzinfo=timezone.utc)

    if not year:
        year = str(use_dt.year)

    month_str = f"{use_dt.month:02d}" if month in ("auto", "prev", "previous", "last", "") else f"{int(month):02d}"
    return month_str, year


def _try_parse_s3_event(event):
    """Return {'bucket':..., 'key':...} if this is an S3 ObjectCreated event, else None."""
    if not isinstance(event, dict):
        return None
    records = event.get("Records") or []
    if not records:
        return None
    rec = records[0]
    if rec.get("eventSource") != "aws:s3":
        return None
    s3p = rec.get("s3") or {}
    bkt = (s3p.get("bucket") or {}).get("name")
    obj = (s3p.get("object") or {}).get("key")
    if not bkt or not obj:
        return None
    return {"bucket": bkt, "key": urllib.parse.unquote_plus(obj)}


def _extract_year_month_from_key(key):
    """
    Try to pull year/month from keys like: uptime/2025/09/.../uptime-report.html
    Returns (month_str, year_str) or None.
    """
    pat = rf"{re.escape(BASE_PREFIX)}/(?P<year>\d{{4}})/(?P<month>\d{{2}})/"
    m = re.search(pat, key)
    if not m:
        return None
    return m.group("month"), m.group("year")


def _get_html(bucket, key):
    obj = s3.get_object(Bucket=bucket, Key=key)
    # Assume UTF-8 report; if binary HTML is possible, consider not decoding and re-uploading the bytes.
    return obj["Body"].read().decode("utf-8", errors="replace")


def _find_latest_report(bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    latest = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            key = obj.get("Key", "")
            if key == f"{prefix}{SRC_FILE_NAME}" or fnmatch.fnmatch(key, f"{prefix}*/{SRC_FILE_NAME}"):
                if (latest is None) or (obj["LastModified"] > latest["LastModified"]):
                    latest = obj
    return latest


def _upload_html_copy(html, year_str, month_str):
    dest_key = f"{BASE_PREFIX}/{year_str}/{month_str}/{OUT_HTML_NAME}"
    s3.put_object(
        Bucket=DEST_BUCKET,
        Key=dest_key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="no-cache"
    )
    _log("info", f"[html] Uploaded -> s3://{DEST_BUCKET}/{dest_key}")


def _render_and_upload_pdf_playwright(html, year_str, month_str):
    """Render with Playwright Chromium if available; return (ok, error_or_None)."""
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:
        msg = ("Playwright not available. Package it (see notes) or set ALLOW_PDF_SKIP=true. "
               f"Import error: {e}")
        _log("warn", msg)
        return False, msg

    pdf_path = "/tmp/uptime-report.pdf"

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--no-sandbox"])
            page = browser.new_page()
            # Safer default in VPC/no-internet environments
            page.set_content(html, wait_until=PLAYWRIGHT_WAIT)
            # Keep colors/backgrounds; prefer CSS @page sizes if present
            page.pdf(path=pdf_path, print_background=True, format=PDF_FORMAT, prefer_css_page_size=True)
            browser.close()

        if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
            raise RuntimeError("Playwright produced no PDF output")

        dest_key = f"{BASE_PREFIX}/{year_str}/{month_str}/{OUT_PDF_NAME}"
        with open(pdf_path, "rb") as f:
            s3.put_object(Bucket=DEST_BUCKET, Key=dest_key, Body=f.read(), ContentType="application/pdf")
        _log("info", f"[pdf] Uploaded -> s3://{DEST_BUCKET}/{dest_key}")
        return True, None

    except Exception as e:
        _log("error", f"PDF generation failed: {repr(e)}")
        return False, str(e)


def _error(code, message):
    _log("error", message)
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message})
    }


def _log(level, msg, **kw):
    print(json.dumps({"level": level, "msg": msg, **kw}))
