# Lambda base (Amazon Linux 2023)
FROM public.ecr.aws/lambda/python:3.12

# Fonts + render libs (no curl drama)
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      xz tar libjpeg-turbo \
    && dnf clean all

# Install wkhtmltopdf (CentOS 8 RPM works on AL2023). Try 0.12.6-1, fall back to 0.12.5-1.
RUN set -eux; \
  RPM1="https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.centos8.x86_64.rpm"; \
  RPM2="https://github.com/wkhtmltopdf/packaging/releases/download/0.12.5-1/wkhtmltox-0.12.5-1.centos8.x86_64.rpm"; \
  dnf -y install "${RPM1}" || dnf -y install "${RPM2}"; \
  /usr/local/bin/wkhtmltopdf --version

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

COPY lambda_function.py .

# tmp dirs for wkhtmltopdf / fontconfig caches
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts

CMD ["lambda_function.lambda_handler"]
