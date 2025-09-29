# Lambda base (AL2023 + Python 3.12)
FROM public.ecr.aws/lambda/python:3.12

# --- Native libs Chromium needs + fonts ---
RUN dnf -y install \
      libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst \
      libXrandr libXScrnSaver pango cairo cairo-gobject gdk-pixbuf2 \
      at-spi2-atk at-spi2-core alsa-lib nss nspr cups-libs \
      libdrm libgbm mesa-libgbm \
      fontconfig freetype harfbuzz fribidi \
      dejavu-sans-mono-fonts dejavu-sans-fonts dejavu-serif-fonts \
      google-noto-sans-fonts google-noto-emoji-color-fonts \
      which unzip tar shadow-utils findutils \
    && dnf clean all

# --- Python deps ---
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Tell Playwright where to place browsers and make dirs writable
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache
RUN mkdir -p /ms-playwright /tmp/.cache/fontconfig && chmod -R 777 /ms-playwright /tmp

# Download Chromium that matches Playwright (NO --with-deps on AL2023)
RUN python -m playwright install chromium

# Function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Lambda entry
CMD ["lambda_function.lambda_handler"]
