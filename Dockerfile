FROM public.ecr.aws/lambda/python:3.12

# Render/runtime deps (no update; no curl replacement to avoid curl-minimal conflicts)
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      tar xz ca-certificates \
      --setopt=install_weak_deps=0 \
 && dnf clean all

# ---- wkhtmltopdf (COPY a tested tar.xz into the image) ----
# Put a working archive in your repo at tools/wkhtmltox.tar.xz
# (from the official wkhtmltopdf "packaging" releases; generic linux amd64 build)
COPY tools/wkhtmltox.tar.xz /tmp/wkhtmltox.tar.xz
RUN set -eux; \
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
