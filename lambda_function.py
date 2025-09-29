import os
import json
import re
import tempfile
from typing import Dict, Any, Iterable
import boto3

ENV = {
    "SRC_BUCKET": os.getenv("SRC_BUCKET", ""),
    "DEST_BUCKET": os.getenv("DEST_BUCKET", ""),
    "BASE_PREFIX": os.getenv("BASE_PREFIX", "uptime"),
    "PDF_FORMAT": os.getenv("PDF_FORMAT", "A4"),
    # page load wait: "load" | "domcontentloaded" | "networkidle"
    "PLAYWRIGHT_WAIT": os.getenv("PLAYWRIGHT_WAIT", "domcontentloaded"),
    # default timeouts (ms)
    "PAGE_TIMEOUT_MS": int(os.getenv("PAGE_TIMEOUT_MS", "20000")),
    # offline by default; set ALLOW_NET=true to allow http(s)
    "ALLOW_NET": os.getenv("ALLOW_NET", "false").lower(),
    # optional allow-list when ALLOW_NET=true (comma-separated host names)
    "ALLOW_HOSTS": os.getenv("ALLOW_HOSTS", ""),  # e.g. "fonts.googleapis.com,fonts.gstatic.com"
    # if true, skip the PDF step (handy for debugging)
    "ALLOW_PDF_SKIP": os.getenv("ALLOW_PDF_SKIP", "false").lower(),
    # Optional AWS region for S3-style absolute URLs in <base>, if you want it
    "AWS_REGION": os.getenv("AWS_REGION", os.getenv("AWS_DEFAULT_REGION", "us-east-1")),
}

s3 = boto3.client("s3")


# ----------------- Helpers -----------------
def _debug_on(event: Any) -> bool:
    """Return True if debug is requested (robust to non-strings)."""
    qs = {}
    if isinstance(event, dict):
        qs = event.get("queryStringParameters") or {}
    dv = qs.get("debug") or (event.get("debug") if isinstance(event, dict) else "")
    try:
        val = str(dv).strip().lower()
    except Exception:
        val = ""
    return val in ("1", "true", "yes", "y", "on")


def _month_year_from_event(event: Dict[str, Any]) -> (str, str):
    """Pull month/year from event with safe defaults (zero-padded month)."""
    mo = str((event.get("month") if isinstance(event, dict) else "") or "").zfill(2) or "01"
    yr = str((event.get("year") if isinstance(event, dict) else "") or "")
    # fallbacks for console-tests without payload
    if not yr:
        yr = "2025"
    if mo == "00":
        mo = "01"
    return mo, yr


def _s3_get_text(bucket: str, key: str) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", "replace")


def _s3_put_bytes(bucket: str, key: str, data: bytes, content_type: str) -> None:
    s3.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        ContentType=content_type,
        CacheControl="no-cache",
    )


def _add_base_href(html: str, base_href: str) -> str:
    """
    Ensure HTML contains a <base href="..."> so relative URLs resolve.
    This helps when you choose to allow network access.
    """
    if not base_href:
        return html
    # If <head> exists, inject a <base> as the first child. Otherwise add a <head>.
    if re.search(r"<head[^>]*>", html, flags=re.I):
        return re.sub(
            r"(?i)(<head[^>]*>)",
            r'\1<base href="%s">' % re.escape(base_href),
            html,
            count=1,
        )
    else:
        return re.sub(
            r"(?i)(<html[^>]*>)",
            r'\1<head><base href="%s"></head>' % re.escape(base_href),
            html,
            count=1,
        )


def _host_in(host: str, allowed: Iterable[str]) -> bool:
    h = host.lower()
    for pat in allowed:
        pat = pat.strip().lower()
        if not pat:
            continue
        if h == pat or h.endswith("." + pat):
            return True
    return False


# --------------- Playwright PDF ---------------
def _render_pdf_playwright(
    html: str,
    out_bucket: str,
    out_key: str,
    pdf_format: str = "A4",
    wait_mode: str = "domcontentloaded",
    timeout_ms: int = 20000,
    allow_net: bool = False,
    allow_hosts: Iterable[str] = (),
) -> None:
    """
    Render HTML -> PDF with Playwright/Chromium.

    Offline by default: blocks all http(s) unless allow_net=True.
    If allow_net=True and allow_hosts is non-empty, only those hosts are allowed.
    """
    from playwright.sync_api import sync_playwright
    from urllib.parse import urlparse

    out_pdf = "/tmp/out.pdf"

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--headless=new",
                "--no-sandbox",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-software-rasterizer",
                "--mute-audio",
                "--single-process",
                "--export-tagged-pdf",
            ],
        )
        context = browser.new_context()
        # Request routing: block external by default
        def _route_handler(route):
            req = route.request
            url = req.url
            if url.startswith("data:") or url.startswith("blob:"):
                return route.continue_()
            if url.startswith("file://"):
                return route.continue_()
            if url.startswith("http://") or url.startswith("https://"):
                if not allow_net:
                    return route.abort()
                if allow_hosts:
                    host = urlparse(url).hostname or ""
                    if not _host_in(host, allow_hosts):
                        return route.abort()
                # allowed
                return route.continue_()
            return route.continue_()

        context.route("**/*", _route_handler)

        try:
            page = context.new_page()
            page.set_default_timeout(timeout_ms)
            page.set_default_navigation_timeout(timeout_ms)
            page.emulate_media(media="screen")
            page.set_content(html, wait_until=wait_mode)

            page.pdf(
                path=out_pdf,
                format=pdf_format,
                print_background=True,
                prefer_css_page_size=True,
                scale=1.0,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
        finally:
            context.close()
            browser.close()

    with open(out_pdf, "rb") as f:
        _s3_put_bytes(out_bucket, out_key, f.read(), "application/pdf")


# --------------- Lambda handler ---------------
def lambda_handler(event, context):
    dbg = _debug_on(event)
    mo, yr = _month_year_from_event(event if isinstance(event, dict) else {})
    prefix = f"{ENV['BASE_PREFIX'].rstrip('/')}/{yr}/{mo}/"

    src_bucket = ENV["SRC_BUCKET"]
    dest_bucket = ENV["DEST_BUCKET"]
    html_key = f"{prefix}uptime-report.html"
    pdf_key = f"{prefix}uptime-report.pdf"

    if not src_bucket or not dest_bucket:
        return _resp(
            500,
            {"error": "SRC_BUCKET and DEST_BUCKET must be set as environment variables."},
        )

    if dbg:
        print(f"[versions] using playwright for PDF")
        print(f"[cfg] SRC_BUCKET='{src_bucket}' DEST_BUCKET='{dest_bucket}' BASE_PREFIX='{ENV['BASE_PREFIX']}'")
        print(f"[src] s3://{src_bucket}/{html_key}")

    # Fetch HTML
    try:
        html = _s3_get_text(src_bucket, html_key)
    except Exception as e:
        return _resp(500, {"error": f"failed to read HTML from s3://{src_bucket}/{html_key}: {e}"})

    # (Optional) put a copy of HTML to destination for auditing/viewing
    try:
        _s3_put_bytes(dest_bucket, html_key, html.encode("utf-8"), "text/html; charset=utf-8")
        if dbg:
            print(f"[html] uploaded -> s3://{dest_bucket}/{html_key}")
    except Exception as e:
        # non-fatal
        print(f"[warn] failed to copy html to dest: {e}")

    # Ensure relative URLs can resolve if you later allow network
    base_url = f"https://{src_bucket}.s3.{ENV['AWS_REGION']}.amazonaws.com/{prefix}"
    html_with_base = _add_base_href(html, base_url)

    # Short-circuit for debug
    if ENV["ALLOW_PDF_SKIP"] == "true":
        return _resp(
            200,
            {
                "src_bucket": src_bucket,
                "dest_bucket": dest_bucket,
                "prefix": prefix,
                "html_key": html_key,
                "dest_html_key": html_key,
                "dest_pdf_key": pdf_key,
                "skipped_pdf": True,
            },
        )

    # Playwright render
    try:
        allow_net = (ENV["ALLOW_NET"] == "true")
        allow_hosts = tuple([h.strip() for h in ENV["ALLOW_HOSTS"].split(",") if h.strip()])
        _render_pdf_playwright(
            html=html_with_base,
            out_bucket=dest_bucket,
            out_key=pdf_key,
            pdf_format=ENV["PDF_FORMAT"],
            wait_mode=ENV["PLAYWRIGHT_WAIT"],
            timeout_ms=ENV["PAGE_TIMEOUT_MS"],
            allow_net=allow_net,
            allow_hosts=allow_hosts,
        )
        if dbg:
            print(f"[pdf] uploaded -> s3://{dest_bucket}/{pdf_key}")
        return _resp(
            200,
            {
                "src_bucket": src_bucket,
                "dest_bucket": dest_bucket,
                "prefix": prefix,
                "html_key": html_key,
                "dest_html_key": html_key,
                "dest_pdf_key": pdf_key,
            },
        )
    except Exception as e:
        print("[error] PDF generation failed")
        import traceback

        traceback.print_exc()
        return _resp(500, {"error": f"PDF generation failed: {e}"})


def _resp(code: int, body: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "statusCode": code,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body),
    }
