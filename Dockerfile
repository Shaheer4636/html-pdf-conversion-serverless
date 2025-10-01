# Lambda base (Amazon Linux 2023)
FROM public.ecr.aws/lambda/python:3.12

# Render deps (fonts, cairo, X libs). Keep it simple; no exotic flags.
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      libjpeg-turbo libpng tar xz ca-certificates \
  && dnf clean all

# Download a generic wkhtmltopdf build at build-time (no repo file needed)
# We use Python's stdlib to avoid curl-minimal conflicts.
RUN set -eux; \
  python - <<'PY' \
import sys,urllib.request,os,subprocess,tarfile
urls=[
 "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.linux-generic-amd64.tar.xz",
 "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1/wkhtmltox-0.12.6.1-linux-generic-amd64.tar.xz",
]
dest="/tmp/wkhtmltox.tar.xz"
for u in urls:
    try:
        with urllib.request.urlopen(u) as r:
            data=r.read()
            if len(data) < 10_000_000:  # sanity: ~50MB expected
                continue
            open(dest,"wb").write(data)
            break
    except Exception as e:
        pass
if not os.path.exists(dest):
    print("FAILED to download wkhtmltopdf tarball", file=sys.stderr); sys.exit(1)
os.makedirs("/opt/wkhtmltox", exist_ok=True)
# extract .tar.xz
subprocess.check_call(["tar","-xJf",dest,"-C","/opt/wkhtmltox","--strip-components=1"])
PY
# symlink so pdfkit can find it
RUN ln -sf /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf \
 && /usr/local/bin/wkhtmltopdf --version

# Python deps
WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

# Your Lambda handler
COPY lambda_function.py .

# env to keep font cache writable in Lambda
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts

CMD [ "lambda_function.handler" ]
