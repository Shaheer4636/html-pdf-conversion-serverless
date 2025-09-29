# Amazon Linux 2023 Lambda base (Python 3.12)
FROM public.ecr.aws/lambda/python:3.12

# Make Playwright put browsers here (bundled into the image)
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# ---- OS libraries that Chromium needs (dnf, not apt) ----
RUN dnf install -y \
    # X / GLib stack
    glib2 dbus-libs \
    libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst libXrandr libXfixes libXrender \
    libdrm mesa-libgbm libxkbcommon \
    nss nspr alsa-lib cups-libs \
    # Text / layout (also helps with fonts)
    pango atk at-spi2-atk \
    # (weasyprint deps kept; harmless)
    cairo cairo-gobject gdk-pixbuf2 fontconfig freetype harfbuzz fribidi libxml2 libxslt \
    libjpeg-turbo libpng zlib \
    wget tar which \
 && dnf clean all

# ---- Python deps ----
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# ---- Download the Chromium binary now (no downloads at runtime) ----
RUN python -m playwright install chromium

# Writable cache for fontconfig at runtime
ENV XDG_CACHE_HOME=/tmp/fontcache
RUN mkdir -p /tmp/fontcache && chmod -R 777 /tmp/fontcache

# Your handler
COPY lambda_function.py /var/task/

CMD ["lambda_function.lambda_handler"]
