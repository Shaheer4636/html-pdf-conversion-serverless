FROM public.ecr.aws/lambda/python:3.12

# Render deps (no full update) and avoid curl-minimal conflicts
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      tar xz ca-certificates curl \
      --setopt=install_weak_deps=False \
      --allowerasing --exclude=curl-minimal \
 && dnf clean all

# --- Fetch wkhtmltox asset dynamically (no hard-coded filename) ---
ARG WKHTML_TAG=0.12.6-1
RUN set -eux; \
    api="https://api.github.com/repos/wkhtmltopdf/packaging/releases/tags/${WKHTML_TAG}"; \
    asset="$(curl -fsSL "$api" \
      | tr -d '\r' \
      | grep -Eo '"browser_download_url":\s*"[^"]+' \
      | cut -d'"' -f4 \
      | grep -E 'linux.*(amd64|x86_64).*\.tar\.xz$' \
      | head -n1)"; \
    test -n "$asset"; echo "Downloading: $asset"; \
    curl -fsSL "$asset" -o /tmp/wkhtmltox.tar.xz; \
    xz -t /tmp/wkhtmltox.tar.xz; \
    mkdir -p /opt/wkhtmltox; \
    tar -xJf /tmp/wkhtmltox.tar.xz -C /opt/wkhtmltox --strip-components=1; \
    ln -sf /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf; \
    /opt/wkhtmltox/bin/wkhtmltopdf --version

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

COPY lambda_function.py .

ENV HOME=/tmp XDG_CACHE_HOME=/tmp FONTCONFIG_PATH=/etc/fonts
CMD [ "lambda_function.lambda_handler" ]
