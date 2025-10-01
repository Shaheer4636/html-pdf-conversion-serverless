FROM public.ecr.aws/lambda/python:3.12

# Minimal render deps & fonts (no curl here)
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      libjpeg-turbo libpng tar xz ca-certificates \
  && dnf clean all

# wkhtmltopdf tarball is prepared by the workflow into ./tools
COPY tools/wkhtmltox.tar.xz /tmp/wkhtmltox.tar.xz
RUN set -eux; \
    test -s /tmp/wkhtmltox.tar.xz; \
    mkdir -p /opt/wkhtmltox; \
    tar -xJf /tmp/wkhtmltox.tar.xz -C /opt/wkhtmltox --strip-components=1; \
    ln -sf /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf; \
    /usr/local/bin/wkhtmltopdf --version

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

COPY lambda_function.py .

ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts

CMD [ "lambda_function.handler" ]
