import json, fnmatch, os
from datetime import datetime, timezone, timedelta

import boto3
from botocore.exceptions import ClientError

def _env(name, default=""):
    v = os.getenv(name, default)
    return v.strip() if isinstance(v, str) else v

# ------- Config (env overrides allowed) -------
BUCKET_NAME_SRC = _env("SRC_BUCKET", "lambda-output-report-000000987123")
DEST_BUCKET     = _env("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX     = _env("BASE_PREFIX", "uptime")

SRC_FILE_NAME   = "uptime-report.html"
OUT_HTML_NAME   = "uptime-report.html"
OUT_PDF_NAME    = "uptime-report.pdf"

ALLOW_PDF_SKIP  = _env("ALLOW_PDF_SKIP", "false").lower() in ("1","true","yes")
DEBUG_DEFAULT   = _env("DEBUG_DEFAULT", "false").lower() in ("1","true","yes")

AWS_REGION      = _env("AWS_REGION", _env("AWS_DEFAULT_REGION", "us-east-1"))
# ---------------------------------------------

s3 = boto3.client("s3")

def handler(event, context):
    debug = _get_debug(event)
    try:
        m, y = _resolve_month_year(event)
    except ValueError as ve:
        return _error(400, str(ve))

    prefix = f"{BASE_PREFIX}/{y}/{m}/"
    status = {
        "month": m, "year": y,
        "src_bucket": BUCKET_NAME_SRC, "dest_bucket": DEST_BUCKET,
        "src_prefix": prefix, "dest_prefix": prefix,
        "html_uploaded": False, "pdf_uploaded": False
    }

    try:
        _log_cfg()
        _assert_bucket_exists(BUCKET_NAME_SRC, "source")
        _ensure_dest_bucket_exists(DEST_BUCKET)

        latest = _find_latest_report(BUCKET_NAME_SRC, prefix)
        if latest is None:
            return _error(404, f'No "{SRC_FILE_NAME}" under s3://{BUCKET_NAME_SRC}/{prefix}')

        key = latest["Key"]
        print(f"[src] using: s3://{BUCKET_NAME_SRC}/{key}")
        obj = s3.get_object(Bucket=BUCKET_NAME_SRC, Key=key)
        html = obj["Body"].read().decode("utf-8", errors="replace")

        _upload_html_copy(html, y, m)
        status["html_uploaded"] = True

        try:
            _render_and_upload_pdf_weasyprint(html, y, m)
            status["pdf_uploaded"] = True
        except Exception as e:
            status["pdf_error"] = str(e)
            if not ALLOW_PDF_SKIP:
                return _error(500, f"PDF generation failed: {e}")

        if debug:
            return {"statusCode": 200, "headers": {"Content-Type": "application/json"}, "body": json.dumps(status)}
        return {"statusCode": 200, "headers": {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}, "body": html}

    except ClientError as e:
        return _error(500, f"S3 error: {e.response.get('Error', {}).get('Message', str(e))}")
    except Exception as e:
        return _error(500, f"Unhandled error: {str(e)}")

def lambda_handler(event, context):
    return handler(event, context)

# -------------- Helpers -----------------

def _get_debug(event):
    d = DEBUG_DEFAULT
    if isinstance(event, dict):
        qs = event.get("queryStringParameters") or {}
        val = (qs.get("debug") or event.get("debug") or "")
        d = str(val).lower() in ("1","true")
    return d

def _resolve_month_year(event):
    event = event or {}; qs = event.get("queryStringParameters") or {}
    def _get(k):
        v = qs.get(k)
        if v is None and isinstance(event, dict): v = event.get(k)
        return (v or "").strip() if isinstance(v, str) else v
    month = (_get("month") or "auto").lower()
    year  = _get("year")
    now = datetime.now(timezone.utc)
    if month in ("auto",""): use_dt = now
    elif month in ("prev","previous","last"):
        use_dt = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    else:
        if not str(month).isdigit() or not (1 <= int(month) <= 12):
            raise ValueError('Invalid "month". Use two digits like "09", or "auto", or "prev".')
        y = int(year) if year else now.year
        use_dt = datetime(y, int(month), 1, tzinfo=timezone.utc)
    if not year: year = str(use_dt.year)
    m = f"{use_dt.month:02d}" if month in ("auto","prev","previous","last","") else f"{int(month):02d}"
    return m, year

def _find_latest_report(bucket, prefix):
    paginator = s3.get_paginator("list_objects_v2")
    latest = None
    for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []) or []:
            k = obj.get("Key", "")
            if k == f"{prefix}{SRC_FILE_NAME}" or fnmatch.fnmatch(k, f"{prefix}*/{SRC_FILE_NAME}"):
                if latest is None or obj["LastModified"] > latest["LastModified"]:
                    latest = obj
    return latest

def _upload_html_copy(html, y, m):
    dest_key = f"{BASE_PREFIX}/{y}/{m}/{OUT_HTML_NAME}"
    s3.put_object(
        Bucket=DEST_BUCKET, Key=dest_key,
        Body=html.encode("utf-8"),
        ContentType="text/html; charset=utf-8",
        CacheControl="no-cache"
    )
    print(f"[html] uploaded -> s3://{DEST_BUCKET}/{dest_key}")

def _render_and_upload_pdf_weasyprint(html, y, m):
    # Writable caches for fontconfig in Lambda
    os.makedirs("/tmp/.cache", exist_ok=True)
    os.environ.setdefault("HOME", "/tmp")
    os.environ.setdefault("XDG_CACHE_HOME", "/tmp/.cache")
    os.environ.setdefault("FONTCONFIG_PATH", "/etc/fonts")
    os.environ.setdefault("FONTCONFIG_FILE", "/etc/fonts/fonts.conf")

    from weasyprint import HTML
    # If your HTML uses relative URLs (e.g., <img src="...">), set base_url to a directory
    pdf_path = "/tmp/uptime-report.pdf"
    HTML(string=html, base_url="/tmp").write_pdf(target=pdf_path)

    if not (os.path.exists(pdf_path) and os.path.getsize(pdf_path) > 0):
        raise RuntimeError("WeasyPrint produced no PDF output")

    dest_key = f"{BASE_PREFIX}/{y}/{m}/{OUT_PDF_NAME}"
    with open(pdf_path, "rb") as f:
        s3.put_object(Bucket=DEST_BUCKET, Key=dest_key, Body=f.read(), ContentType="application/pdf")
    print(f"[pdf] uploaded -> s3://{DEST_BUCKET}/{dest_key}")

def _assert_bucket_exists(bucket, label="bucket"):
    try:
        s3.head_bucket(Bucket=bucket)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg  = e.response.get("Error", {}).get("Message", str(e))
        if code in ("404","NoSuchBucket","NotFound"):
            raise RuntimeError(f"{label.capitalize()} bucket '{bucket}' does not exist.")
        if code in ("301","PermanentRedirect"):
            raise RuntimeError(f"{label.capitalize()} bucket '{bucket}' exists in a different region than {AWS_REGION}.")
        if code in ("403","AccessDenied"):
            raise RuntimeError(f"Access denied to {label} bucket '{bucket}'.")
        raise RuntimeError(f"S3 head_bucket failed for '{bucket}': {code} {msg}")

def _ensure_dest_bucket_exists(bucket):
    try:
        s3.head_bucket(Bucket=bucket)
        print(f"[cfg] dest bucket ok: {bucket}")
        return
    except ClientError as e:
        if e.response.get("Error", {}).get("Code", "") not in ("404","NoSuchBucket","NotFound"):
            msg = e.response.get("Error", {}).get("Message", str(e))
            raise RuntimeError(f"S3 head_bucket failed for destination '{bucket}': {msg}")
    print(f"[cfg] creating destination bucket: {bucket} in {AWS_REGION}")
    if AWS_REGION == "us-east-1":
        s3.create_bucket(Bucket=bucket)
    else:
        s3.create_bucket(Bucket=bucket, CreateBucketConfiguration={"LocationConstraint": AWS_REGION})

def _log_cfg():
    print(f"[cfg] SRC_BUCKET={BUCKET_NAME_SRC!r} DEST_BUCKET={DEST_BUCKET!r} BASE_PREFIX={BASE_PREFIX!r} REGION={AWS_REGION!r}")

def _error(code, message):
    print(f"[error] {message}")
    return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": json.dumps({"error": message})}
