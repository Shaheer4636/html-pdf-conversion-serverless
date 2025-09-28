# lambda_function.py
import json
import fnmatch
import os
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

# ====== CONFIG (env overrides) ======
BUCKET_NAME_SRC = os.getenv("SRC_BUCKET", "lambda-output-report-000000987123")
DEST_BUCKET     = os.getenv("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX     = os.getenv("BASE_PREFIX", "uptime")

SRC_FILE_NAME   = "uptime-report.html"   # file to find in source
OUT_HTML_NAME   = "uptime-report.html"   # HTML name on destination
OUT_PDF_NAME    = "uptime-report.pdf"    # PDF name on destination

# Behavior toggles
ALLOW_PDF_SKIP  = os.getenv("ALLOW_PDF_SKIP", "false").lower() in ("1","true","yes")
DEBUG_DEFAULT   = os.getenv("DEBUG_DEFAULT", "false").lower() in ("1","true","yes")
PLAYWRIGHT_WAIT = os.getenv("PLAYWRIGHT_WAIT", "domcontentloaded")
PDF_FORMAT      = os.getenv("PDF_FORMAT", "A4")
# ====================================

s3 = boto3.client("s3")


def handler(event, context):
    """
    Inputs:
      - Query string: ?month=09&year=2025[&debug=1]
      - Event JSON:   {"month":"09","year":"2025","debug":1}
      - month=auto (default), month=prev supported

    Flow:
      1) Read newest uptime/<year>/<month>/**/uptime-report.html from source bucket.
      2) Upload HTML copy to s3://DEST_BUCKET/uptime/<year>/<month>/uptime-report.html
      3) Render to PDF (Playwright Chromium) and upload to .../uptime-report.pdf
      4) Return HTML (or JSON status if debug=1).
    """
    debug = _get_debug(event)

    try:
        month_str, year_str = _resolve_month_year(event)
    except ValueError as ve:
        return _error(400, str(ve))

    prefix = f"{BASE_PREFIX}/{year_str}/{month_str}/"
    status = {
        "month": month_str, "year": year_str,
        "src_bucket": BUCKET_NAME_SRC, "dest_bucket": DEST_BUCKET,
        "src_prefix": prefix, "dest_prefix": prefix,
        "html_uploaded": False, "pdf_uploaded": False
    }

    # Log effective config and hard-fail if buckets are wrong
    try:
        _log_cfg()
        _head_bucket_or_raise(BUCKET_NAME_SRC)
        _head_bucket_or_raise(DEST_BUCKET)
    except RuntimeError as e:
        return _error(404, str(e))

    try:
        # 1) Find newest HTML
        latest = _find_latest_report(BUCKET_NAME_SRC, prefix)
        if latest is None:
            return _error(
                404,
                f'No "{SRC_FILE_NAME}" found under s3://{BUCKET_NAME_SRC}/{prefix} (including subfolders).'
            )

        key = latest["Key"]
        status["src_key"] = key
        print(f"[src] Using latest object: s3://{BUCKET_NAME_SRC}/{key}")

        obj = s3.get_object(Bucket=BUCKET_NAME_SRC, Key=key)
        html = obj["Body"].read().decode("utf-8", errors="replace")

        # 2) Save HTML copy
        _upload_html_copy(html, year_str, month_str)
        status["html_uploaded"] = True

        # 3) Render PDF using Playwright Chromium
        try:
            _render_and_upload_pdf_playwright(html, year_str, month_str)
            status["pdf_uploaded"] = True
        except Exception as e:
            status["pdf_error"] = str(e)
            if not ALLOW_PDF_SKIP:
                return _error(500, f"PDF generation failed: {e}")

        # 4) Response
        if debug:
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
        return _error(500, f"S3 error: {msg}")
    except Exception as e:
        return _error(500, f"Unhandled error: {str(e)}")


def lambda_handler(event, context):  # console entrypoint
    return handler(event, context)


# ---------- helpers ----------

def _get_debug(event):
    debug = DEBUG_DEFAULT
    if isinstance(event, dict):
        qs = event.get("queryStringParameters") or {}
        debug_val = (qs.get("debug") or event.get("debug") or "")
        debug = str(debug_val).lower() in ("1", "true")
    return debug


def _resolve_month_year(event):
    event = event or {}
    qs = event.get("queryStringParameters") or {}

    def _get(key):
        v = qs.get(key)
        if v is None and isinstance(event, dict):
            v = event.get(key)
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
        if not str(month).isdigit() or not (1 <= int(month) <= 12):
            raise ValueError('Invalid "month". Use two digits like "09", or "auto", or "prev".')
        y = int(year) if year else now.year
        use_dt = datetime(y, int(month), 1, tzinfo=timezone.utc)

    if not year:
        year = str(use_dt.year)

    month_str = f"{use_dt.month:02d}" if month in ("auto", "prev", "previous", "last", "") else f"{int(month):02d}"
    return month_str, year


def _find_latest_report(bucket, prefix):
    """
    Returns the newest object dict for:
      - {prefix}/uptime-report.html
      - {prefix}*/uptime-report.html   (one more subdirectory)
    """
    paginator = s3.get_paginator("list_objects_v2")
    pages = paginator.paginate(Bucket=bucket, Prefix=prefix)

    latest = None
    for page in pages:
        contents = page.get("Contents", [])
        if not contents:
            continue
        candidates = []
        for obj in contents:
            key = obj.get("Key", "")
            if key == f"{prefix}{SRC_FILE_NAME}":
                candidates.append(obj)
            elif fnmatch.fnmatch(key, f"{prefix}*/{SRC_FILE_NAME}"):
                candidates.append(obj)
        if candidates:
            candidates.sort(key=lambda o: o["LastModified"], reverse=True)
            pick = candidates[0]
            if (latest is None) or (pick["LastModified"] > latest["LastModified"]):
                latest = pick
    return latest


def _upload_html_copy(html, year_str, month_str):
    dest_key = f"{BASE_PREFIX}/{year_str}/{month_str}/{OUT_HTML_NAME}"
    try:
        s3.put_object(
            Bucket=DEST_BUCKET,
            Key=dest_key,
            Body=html.encode("utf-8"),
            ContentType="text/html; charset=utf-8",
            CacheControl="no-cache"
        )
    except ClientError as e:
        msg = e.response.get("Error", {}).get("Message", str(e))
        raise RuntimeError(f"Writing HTML to s3://{DEST_BUCKET}/{dest_key} failed: {msg}")
    print(f"[html] Uploaded HTML -> s3://{DEST_BUCKET}/{dest_key}")


def _render_and_upload_pdf_playwright(html, year_str, month_str):
    """
    Uses Playwright (Chromium) bundled in the container image to render the HTML and save as PDF.
    """
    from playwright.sync_api import sync_playwright

    pdf_path = "/tmp/uptime-report.pdf"
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        page = browser.new_page()
        page.set_content(html, wait_until=PLAYWRIGHT_WAIT)
        page.pdf(path=pdf_path, print_background=True, format=PDF_FORMAT)
        browser.close()

    if not os.path.exists(pdf_path) or os.path.getsize(pdf_path) == 0:
        raise RuntimeError("Playwright produced no PDF output")

    dest_key = f"{BASE_PREFIX}/{year_str}/{month_str}/{OUT_PDF_NAME}"
    try:
        with open(pdf_path, "rb") as f:
            s3.put_object(Bucket=DEST_BUCKET, Key=dest_key, Body=f.read(), ContentType="application/pdf")
    except ClientError as e:
        msg = e.response.get("Error", {}).get("Message", str(e))
        raise RuntimeError(f"Writing PDF to s3://{DEST_BUCKET}/{dest_key} failed: {msg}")
    print(f"[pdf] Uploaded PDF -> s3://{DEST_BUCKET}/{dest_key}")


def _head_bucket_or_raise(bucket):
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg  = e.response.get("Error", {}).get("Message", str(e))
        raise RuntimeError(f"S3 head_bucket failed for '{bucket}': {code} {msg}")


def _log_cfg():
    print(f"[cfg] SRC_BUCKET={BUCKET_NAME_SRC!r} DEST_BUCKET={DEST_BUCKET!r} BASE_PREFIX={BASE_PREFIX!r}")


def _error(code, message):
    print(f"[error] {message}")
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": message})
    }
