# Lambda base (AL2023 + Python 3.12)
FROM public.ecr.aws/lambda/python:3.12

# --- System deps for Chromium, fonts, fontconfig cache ---
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
# Playwright drives the bundled Chromium; boto3 is in the base image, but pin for safety if you want
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Download Chromium that matches Playwright and all runtime deps
RUN python -m playwright install --with-deps chromium

# Make sure fontconfig has a writable cache at runtime
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN mkdir -p /tmp/.cache/fontconfig /tmp/.cache/ms-playwright && chmod -R 777 /tmp

# Your function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Lambda entry
CMD ["lambda_function.lambda_handler"]
