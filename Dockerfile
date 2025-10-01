# Lambda base (Amazon Linux 2023)
FROM public.ecr.aws/lambda/python:3.12

# Render deps (fonts, cairo, X libs)
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      libjpeg-turbo libpng tar xz ca-certificates \
  && dnf clean all

# Download wkhtmltopdf at build time using Python stdlib (no curl flags drama)
RUN set -eux; \
  python - <<'PY'
import sys, os, urllib.request, subprocess
urls = [
  "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-2/wkhtmltox-0.12.6-2.linux-generic-amd64.tar.xz",
  "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.linux-generic-amd64.tar.xz",
  "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1/wkhtmltox-0.12.6.1-linux-generic-amd64.tar.xz",
  "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.5-1/wkhtmltox-0.12.5-1.linux-generic-amd64.tar.xz",
]
dest = "/tmp/wkhtmltox.tar.xz"
for u in urls:
    try:
        with urllib.request.urlopen(u, timeout=60) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(1<<20)
                if not chunk: break
                f.write(chunk)
        if os.path.getsize(dest) > 10_000_000:
            break
    except Exception:
        try: os.remove(dest)
        except: pass
        dest = "/tmp/wkhtmltox.tar.xz"
        continue
if not (os.path.exists(dest) and os.path.getsize(dest) > 10_000_000):
    print("FAILED to download wkhtmltopdf tarball", file=sys.stderr); sys.exit(1)
os.makedirs("/opt/wkhtmltox", exist_ok=True)
subprocess.check_call(["tar","-xJf",dest,"-C","/opt/wkhtmltox","--strip-components=1"])
PY

# symlink so pdfkit finds it; verify version
RUN ln -sf /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf \
 && /usr/local/bin/wkhtmltopdf --version

# Python deps
WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

# Lambda handler
COPY lambda_function.py .

# font caches go to /tmp in Lambda
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts

CMD [ "lambda_function.handler" ]
