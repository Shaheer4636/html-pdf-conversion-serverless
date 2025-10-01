# Lambda Python 3.12 on Amazon Linux 2023
FROM public.ecr.aws/lambda/python:3.12

# Rendering deps + fonts (no curl to avoid curl-minimal drama)
RUN dnf -y install \
      fontconfig freetype cairo harfbuzz \
      dejavu-sans-fonts dejavu-serif-fonts \
      liberation-sans-fonts liberation-serif-fonts \
      libX11 libXext libXrender libXau libXdmcp \
      libjpeg-turbo \
      xz tar ca-certificates \
      --setopt=install_weak_deps=0 \
    && dnf clean all

# --- wkhtmltopdf RPM is downloaded by the GitHub Action into ./tools/wkhtmltox.rpm
#     We install it here locally so it lives in /usr/local/bin/wkhtmltopdf
COPY tools/wkhtmltox.rpm /tmp/wkhtmltox.rpm
RUN dnf -y install /tmp/wkhtmltox.rpm --setopt=install_weak_deps=0 && dnf clean all \
 && rm -f /tmp/wkhtmltox.rpm \
 # sanity
 && (command -v wkhtmltopdf && wkhtmltopdf --version) || true

# App code + deps
WORKDIR /var/task
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt -t .
COPY lambda_function.py .

# Runtime env
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    FONTCONFIG_PATH=/etc/fonts \
    WKHTMLTOPDF_BIN=/usr/local/bin/wkhtmltopdf

# Lambda entrypoint
CMD ["lambda_function.lambda_handler"]
