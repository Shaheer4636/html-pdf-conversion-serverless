# Lambda base (Amazon Linux 2023, Python 3.12)
FROM public.ecr.aws/lambda/python:3.12

# Keep browser in a fixed, read-only path
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1 \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp

# --- System libraries Chromium needs on AL2023 ---
RUN dnf install -y \
    at-spi2-atk at-spi2-core atk \
    alsa-lib \
    cairo pango gdk-pixbuf2 \
    cups-libs dbus-libs expat glib2 \
    libX11 libXcomposite libXcursor libXdamage libXext \
    libXi libXrandr libXrender libXScrnSaver libXtst \
    libdrm mesa-libgbm \
    nss nspr \
    freetype fontconfig \
    libjpeg-turbo libpng zlib \
  && dnf clean all

# Optional: a place for custom fonts (won’t fail if empty)
RUN mkdir -p /usr/share/fonts/custom

# Python deps
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Download Chromium once at build-time (no apt, just the browser files)
RUN python -m playwright install chromium

# App code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Lambda entrypoint
CMD ["lambda_function.lambda_handler"]
