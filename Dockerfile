# Amazon Linux 2023 Lambda base (Python 3.12)
FROM public.ecr.aws/lambda/python:3.12

# ---- OS libs headless Chromium needs + fonts ----
RUN dnf install -y \
    # rendering stack
    cairo cairo-gobject pango gdk-pixbuf2 \
    libjpeg-turbo libpng zlib \
    fontconfig freetype harfbuzz fribidi \
    libxml2 libxslt \
    # common chromium run deps
    atk at-spi2-atk at-spi2-core cups-libs nspr nss \
    libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst \
    libdrm mesa-libgbm \
  && dnf clean all && rm -rf /var/cache/dnf

# ---- Python deps ----
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Make Playwright always use a fixed, baked-in path for browsers
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Install the Chromium binary once at build time (goes to /ms-playwright)
RUN python -m playwright install chromium

# Writable font cache for fontconfig at runtime (kept in /tmp)
ENV XDG_CACHE_HOME=/tmp/fontcache
RUN mkdir -p /tmp/fontcache && chmod 777 /tmp/fontcache

# ---- App code ----
COPY lambda_function.py /var/task/

# Lambda entry
CMD ["lambda_function.lambda_handler"]
