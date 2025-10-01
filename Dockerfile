# Dockerfile
FROM public.ecr.aws/lambda/python:3.12

# System deps for fonts/rendering and tools for extracting .tar.xz
RUN dnf -y update && dnf -y install \
    fontconfig freetype \
    dejavu-sans-fonts dejavu-serif-fonts \
    liberation-sans-fonts liberation-serif-fonts \
    libX11 libXext libXrender libXau libXdmcp \
    tar xz \
 && dnf clean all

# --- Robust wkhtmltopdf install (keep lib/ next to bin/) ---
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
    # DO NOT copy the binary (it needs ../lib). Use a symlink:
    ln -sf /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf; \
    /opt/wkhtmltox/bin/wkhtmltopdf --version

# App deps
WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

# App code
COPY lambda_function.py .

# runtime env
ENV HOME=/tmp XDG_CACHE_HOME=/tmp FONTCONFIG_PATH=/etc/fonts

# Lambda entrypoint
CMD [ "lambda_function.lambda_handler" ]
