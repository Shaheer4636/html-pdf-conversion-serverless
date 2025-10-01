FROM public.ecr.aws/lambda/python:3.12

# Fonts + X libs + tools
RUN dnf -y update && dnf -y install \
    fontconfig freetype \
    dejavu-sans-fonts dejavu-serif-fonts \
    liberation-sans-fonts liberation-serif-fonts \
    libX11 libXext libXrender libXau libXdmcp \
    tar xz \
 && dnf clean all

# --- Robust wkhtmltopdf install (static linux-generic build) ---
RUN set -eux; \
    urls="\
      https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.linux-generic-amd64.tar.xz \
      https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6.1/wkhtmltox-0.12.6.1-linux-generic-amd64.tar.xz \
      https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.linux-generic-x86_64.tar.xz \
    "; \
    for u in $urls; do \
      echo "Trying $u"; \
      if curl -fSLS "$u" -o /tmp/wkhtmltox.tar.xz; then \
        if xz -t /tmp/wkhtmltox.tar.xz; then \
          echo "Downloaded valid .xz"; \
          break; \
        fi; \
      fi; \
      rm -f /tmp/wkhtmltox.tar.xz || true; \
    done; \
    test -s /tmp/wkhtmltox.tar.xz; \
    mkdir -p /opt/wkhtmltox; \
    tar -xJf /tmp/wkhtmltox.tar.xz -C /opt/wkhtmltox --strip-components=1; \
    install -m 0755 /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf; \
    /usr/local/bin/wkhtmltopdf --version
# --- end wkhtmltopdf install ---

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

COPY lambda_function.py .

ENV HOME=/tmp XDG_CACHE_HOME=/tmp FONTCONFIG_PATH=/etc/fonts

CMD [ "lambda_function.lambda_handler" ]
