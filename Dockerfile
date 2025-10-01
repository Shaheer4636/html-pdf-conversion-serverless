# Lambda base (Amazon Linux 2023 + Python 3.12)
FROM public.ecr.aws/lambda/python:3.12

# --- system deps wkhtmltopdf needs (fonts, X libs, tar/xz, ar for .deb fallback) ---
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      libjpeg-turbo \
      tar xz binutils \
  && dnf clean all

# --- Download & install wkhtmltopdf into /usr/local (with multiple fallbacks) ---
# We avoid curl flags drama by using POSIX shell + curl once; if tarballs 404,
# we fall back to a Debian .deb and unpack it with ar + tar.
RUN set -eux; \
  tmp=/tmp/wkhtmltox; mkdir -p "$tmp"; cd "$tmp"; \
  got=0; \
  for url in \
    "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.linux-generic-amd64.tar.xz" \
    "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-2/wkhtmltox-0.12.6-2.linux-generic-amd64.tar.xz" \
    "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.5-1/wkhtmltox-0.12.5-1.linux-generic-amd64.tar.xz" \
  ; do \
    echo "Trying $url"; \
    if curl -fsSL "$url" -o pkg.tar.xz; then \
      if xz -t pkg.tar.xz 2>/dev/null; then \
        mkdir -p /opt/wkhtmltox; \
        tar -xJf pkg.tar.xz -C /opt/wkhtmltox --strip-components=1; \
        ln -sf /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf; \
        /usr/local/bin/wkhtmltopdf --version; \
        got=1; break; \
      fi; \
    fi; \
    rm -f pkg.tar.xz || true; \
  done; \
  if [ "$got" -eq 0 ]; then \
    echo "Tarballs failed; trying Debian .deb fallback"; \
    for deb in \
      "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox_0.12.6-1.buster_amd64.deb" \
      "https://github.com/wkhtmltopdf/packaging/releases/download/0.12.5-1/wkhtmltox_0.12.5-1.buster_amd64.deb" \
    ; do \
      echo "Trying $deb"; \
      if curl -fsSL "$deb" -o pkg.deb; then \
        ar x pkg.deb data.tar.xz || true; \
        [ -s data.tar.xz ] || { rm -f pkg.deb data.tar.xz; continue; }; \
        tar -xJf data.tar.xz -C /; \
        /usr/local/bin/wkhtmltopdf --version; \
        got=1; break; \
      fi; \
      rm -f pkg.deb data.tar.xz || true; \
    done; \
  fi; \
  if [ "$got" -ne 1 ]; then \
    echo "FATAL: could not install wkhtmltopdf" >&2; exit 1; \
  fi; \
  rm -rf "$tmp"

# --- Python deps ---
WORKDIR /var/task
COPY requirements.txt .
RUN pip install -r requirements.txt --target .

# --- App code ---
COPY lambda_function.py .

# Environment hardening for font caches etc.
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts \
    WKHTMLTOPDF_BIN=/usr/local/bin/wkhtmltopdf

# Lambda handler
CMD [ "lambda_function.lambda_handler" ]
