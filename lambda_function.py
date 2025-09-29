import os, json, re, boto3
from urllib.parse import urljoin
from playwright.sync_api import sync_playwright

# --------- config ----------
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")
PDF_FORMAT  = os.environ.get("PDF_FORMAT", "A4")  # or "Letter"
WAIT_UNTIL  = os.environ.get("PLAYWRIGHT_WAIT", "networkidle")
ALLOW_NET   = os.environ.get("ALLOW_NET", "true").lower() == "true"

# Pin browser location (we set this in the Dockerfile)
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")

s3 = boto3.client("s3")


def _keys(evt):
    y = str(evt.get("year")  or "")
    m = str(evt.get("month") or "")
    if not y or not m:
        import datetime as dt
        now = dt.datetime.utcnow()
        y = y or str(now.year)
        m = m or f"{now.month:02d}"
    prefix = f"{BASE_PREFIX}/{y}/{m}/"
    return prefix, f"{prefix}uptime-report.html", f"{prefix}uptime-report.pdf"


def _presigned_url(bucket, key, seconds=600):
    return s3.generate_presigned_url(
        "get_object",
        Params={"Bucket": bucket, "Key": key},
        ExpiresIn=seconds,
    )


def _download_html(bucket, key) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", "replace")


def _absolutize_html(html: str, base_href: str) -> str:
    # Inject <base href> so relative src/href resolve
    if "<head" in html.lower():
        html = re.sub(r"(?i)(<head[^>]*>)", r'\1<base href="%s"/>' % base_href, html, count=1)
    else:
        html = '<head><base href="%s"/></head>' % base_href + html
    return html


def _upload_pdf(bucket, key, data: bytes):
    s3.put_object(Bucket=bucket, Key=key, Body=data, ContentType="application/pdf")


def _render_pdf_from_url(url: str) -> bytes:
    args = [
        "--headless=new",
        "--no-sandbox", "--disable-setuid-sandbox",
        "--disable-gpu", "--disable-dev-shm-usage",
        "--disable-breakpad", "--no-first-run", "--no-default-browser-check",
        "--disable-extensions", "--disable-background-networking",
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        try:
            ctx = browser.new_context(ignore_https_errors=True)
            if not ALLOW_NET:
                ctx.route("**/*", lambda r: r.abort() if r.request.url.startswith(("http://","https://")) else r.continue_())
            page = ctx.new_page()
            page.set_default_navigation_timeout(45000)
            page.emulate_media(media="print")
            page.goto(url, wait_until=WAIT_UNTIL)
            return page.pdf(
                format=PDF_FORMAT,
                print_background=True,
                prefer_css_page_size=True,
                margin={"top":"0","right":"0","bottom":"0","left":"0"},
                scale=1.0,
            )
        finally:
            browser.close()


def _render_pdf_from_html(html: str, base_href: str) -> bytes:
    args = [
        "--headless=new",
        "--no-sandbox", "--disable-setuid-sandbox",
        "--disable-gpu", "--disable-dev-shm-usage",
        "--disable-breakpad", "--no-first-run", "--no-default-browser-check",
    ]
    with sync_playwright() as p:
        browser = p.chromium.launch(args=args)
        try:
            ctx = browser.new_context(ignore_https_errors=True)
            page = ctx.new_page()
            page.set_default_navigation_timeout(45000)
            page.emulate_media(media="print")
            page.set_content(_absolutize_html(html, base_href.rstrip('/') + '/'),
                             wait_until=WAIT_UNTIL)
            return page.pdf(
                format=PDF_FORMAT,
                print_background=True,
                prefer_css_page_size=True,
                margin={"top":"0","right":"0","bottom":"0","left":"0"},
                scale=1.0,
            )
        finally:
            browser.close()


def lambda_handler(event, _ctx=None):
    try:
        prefix, html_key, pdf_key = _keys(event or {})
        url = _presigned_url(SRC_BUCKET, html_key, seconds=600)
        pdf = _render_pdf_from_url(url)  # preferred: identical to Ctrl+P
    except Exception as primary_error:
        try:
            html = _download_html(SRC_BUCKET, html_key)
            base_href = f"https://{SRC_BUCKET}.s3.amazonaws.com/{prefix}"
            pdf = _render_pdf_from_html(html, base_href)
        except Exception as secondary_error:
            return {
                "statusCode": 500,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": f"PDF generation failed: {primary_error} | fallback: {secondary_error}"}),
            }

    _upload_pdf(DEST_BUCKET, pdf_key, pdf)
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({
            "src_bucket": SRC_BUCKET,
            "dest_bucket": DEST_BUCKET,
            "prefix": prefix,
            "html_key": html_key,
            "dest_pdf_key": pdf_key,
        }),
    }
