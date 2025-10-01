# Lambda base (Amazon Linux 2023)
FROM public.ecr.aws/lambda/python:3.12

# Fonts + render libs
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      xz tar libjpeg-turbo \
    && dnf clean all

# 1) Download wkhtmltopdf RPM (Python stdlib; robust to curl-minimal conflicts)
RUN python - <<'PY'
import os, ssl, urllib.request, shutil, sys
urls = [
  "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.centos8.x86_64.rpm",
  "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.5-1/wkhtmltox-0.12.5-1.centos8.x86_64.rpm",
]
dest = "/tmp/wkhtmltox.rpm"
ctx = ssl.create_default_context()
for u in urls:
    try:
        with urllib.request.urlopen(u, context=ctx, timeout=120) as r, open(dest, "wb") as f:
            shutil.copyfileobj(r, f)
        if os.path.getsize(dest) > 10_000_000:
            break
    except Exception:
        try: os.remove(dest)
        except: pass
        dest = "/tmp/wkhtmltox.rpm"
        continue
if not (os.path.exists(dest) and os.path.getsize(dest) > 10_000_000):
    print("FATAL: could not download wkhtmltopdf RPM", file=sys.stderr); sys.exit(1)
PY

# 2) Install the RPM locally and verify
RUN dnf -y install /tmp/wkhtmltox.rpm && /usr/local/bin/wkhtmltopdf --version

# App deps
WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

# App code
COPY lambda_function.py .

# tmp dirs for wkhtmltopdf / fontconfig caches
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts

CMD ["lambda_function.lambda_handler"]
