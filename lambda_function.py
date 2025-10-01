import os
import json
from datetime import datetime
import boto3
from botocore.exceptions import ClientError
from playwright.sync_api import sync_playwright, Error as PWError

# ---------- env ----------
SRC_BUCKET  = os.environ.get("SRC_BUCKET",  "lambda-output-report-000000987123")
DEST_BUCKET = os.environ.get("DEST_BUCKET", "pdf-uptime-reports-0000009")
BASE_PREFIX = os.environ.get("BASE_PREFIX", "uptime")

PDF_FORMAT = os.environ.get("PDF_FORMAT", "A4")
PLAYWRIGHT_WAIT = os.environ.get("PLAYWRIGHT_WAIT", "networkidle").lower()
EXTRA_DELAY_MS = int(os.environ.get("EXTRA_DELAY_MS", "0"))

s3 = boto3.client("s3")

def _ym(event: dict):
    now = datetime.utcnow()
    return (str(event.get("year") or now.year).zfill(4),
            str(event.get("month") or now.month).zfill(2))

def _key(prefix: str, y: str, m: str, name: str) -> str:
    return f"{prefix}/{y}/{m}/{name}".lstrip("/")

def _s3_text(bucket: str, key: str) -> str:
    obj = s3.get_object(Bucket=bucket, Key=key)
    return obj["Body"].read().decode("utf-8", errors="ignore")

def _find_headless_shell():
    # Try to locate a headless shell binary inside the Playwright bundle
    root = os.environ.get("PLAYWRIGHT_BROWSERS_PATH", "/ms-playwright")
    if not os.path.isdir(root):
        return None
    try:
        for d in os.listdir(root):
            base = os.path.join(root, d, "chrome-linux")
            if not os.path.isdir(base):
                continue
            for cand in ("headless_shell", "chrome-headless-shell"):
                p = os.path.join(base, cand)
                if os.path.exists(p) and os.access(p, os.X_OK):
                    return p
    except Exception:
        pass
    return None

def _launch_browser(pw):
    """Launch Chromium in a way that survives Lambda's sandbox.
       Try strong software paths first; fall back to headless_shell if present."""
    base_args = [
        "--no-sandbox",
        "--disable-setuid-sandbox",
        "--disable-dev-shm-usage",
        "--headless=new",                 # force new headless (prevents legacy GPU dance)
        "--ozone-platform=headless",
        "--use-angle=swiftshader",
        "--use-gl=swiftshader",
        "--disable-gpu-compositing",
        "--enable-automation",
        "--no-zygote",
        "--single-process",               # keep everything in one process to avoid GPU host
        "--disable-features=VizDisplayCompositor,Translate,MediaRouter",
    ]

    # Attempt 1: stock Chromium from Playwright bundle
    try:
        return pw.chromium.launch(headless=True, args=base_args)
    except Exception:
        # Attempt 2: headless_shell binary if bundled
        hs = _find_headless_shell()
        if hs:
            return pw.chromium.launch(executable_path=hs, headless=True, args=[
                a for a in base_args if not a.startswith("--headless=")
            ] + ["--headless=new"])
        # Re-raise the original if no fallback
        raise

def lambda_handler(event, context=None):
    try:
        event = event or {}
        year, month = _ym(event)

        html_key = event.get("html_key") or _key(BASE_PREFIX, year, month, "uptime-report.html")
        pdf_key  = event.get("pdf_key")  or _key(BASE_PREFIX, year, month, "uptime-report.pdf")

        # 1) Read HTML from source bucket
        try:
            html = _s3_text(SRC_BUCKET, html_key)
        except ClientError as e:
            return {
                "statusCode": 404,
                "headers": {"Content-Type": "application/json"},
                "body": json.dumps({"error": f"Missing {SRC_BUCKET}/{html_key}", "detail": str(e)})
            }

        # 2) Copy HTML to dest (non-fatal if it fails)
        try:
            s3.copy_object(
                CopySource={"Bucket": SRC_BUCKET, "Key": html_key},
                Bucket=DEST_BUCKET, Key=html_key,
                MetadataDirective="REPLACE",
                ContentType="text/html; charset=utf-8",
            )
        except ClientError:
            pass

        # 3) Render to PDF with Playwright
        base_dir = html_key.rsplit("/", 1)[0] + "/"
        base_url = f"https://{SRC_BUCKET}.s3.amazonaws.com/{base_dir}"

        wait_until = PLAYWRIGHT_WAIT if PLAYWRIGHT_WAIT in {"load", "domcontentloaded", "networkidle"} else "networkidle"

        with sync_playwright() as pw:
            browser = _launch_browser(pw)
            try:
                context = browser.new_context(
                    viewport={"width": 1280, "height": 1920},
                    device_scale_factor=1.0,
                    java_script_enabled=True,
                    base_url=base_url,
                )
                page = context.new_page()
                # Set content and wait for JS to finish networking
                page.set_content(html, wait_until=wait_until, timeout=120_000)

                if EXTRA_DELAY_MS > 0:
                    page.wait_for_timeout(EXTRA_DELAY_MS)

                pdf_bytes = page.pdf(
                    format=PDF_FORMAT,
                    print_background=True,
                    prefer_css_page_size=True,
                    margin={"top": "0.4in", "right": "0.4in", "bottom": "0.6in", "left": "0.4in"},
                    scale=1.0,
                    display_header_footer=False,
                    timeout=120_000,
                )
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

        # 4) Upload PDF
        s3.put_object(
            Bucket=DEST_BUCKET,
            Key=pdf_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )

        return {
            "statusCode": 200,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({
                "src_bucket": SRC_BUCKET,
                "dest_bucket": DEST_BUCKET,
                "prefix": f"{BASE_PREFIX}/{year}/{month}/",
                "html_key": html_key,
                "dest_html_key": html_key,
                "dest_pdf_key": pdf_key,
                "wait_until": wait_until,
                "extra_delay_ms": EXTRA_DELAY_MS,
                "format": PDF_FORMAT,
            }),
        }

    except PWError as e:
        # Playwright-specific errors (clean message)
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"PDF generation failed: {e.__class__.__name__}: {e}"})
        }
    except Exception as e:
        # Anything else
        return {
            "statusCode": 500,
            "headers": {"Content-Type": "application/json"},
            "body": json.dumps({"error": f"PDF generation failed: {e.__class__.__name__}: {e}"})
        }
