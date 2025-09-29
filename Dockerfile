# Amazon Linux 2023 + Python 3.12 Lambda base
FROM public.ecr.aws/lambda/python:3.12

# Writable caches in Lambda runtime
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1

# ---- System libs Chromium needs on AL2023 (dnf, NOT apt) ----
RUN dnf install -y \
    # X / input / windowing
    libX11 libXcomposite libXcursor libXdamage libXext libXi libXrandr libXrender libXScrnSaver libXtst \
    libxkbcommon \
    # graphics
    libdrm mesa-libgbm \
    # text / fonts / rendering
    pango cairo gdk-pixbuf2 freetype fontconfig \
    # sound (Chromium expects it present even in headless)
    alsa-lib \
    # misc
    nss nspr cups-libs dbus-libs expat glib2 zlib libjpeg-turbo libpng \
    at-spi2-core at-spi2-atk atk \
  && dnf clean all

# (optional) where you can COPY custom fonts if you have them
RUN mkdir -p /usr/share/fonts/custom && fc-cache -f

# Python deps
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Download Chromium at build time (no network at runtime)
RUN python -m playwright install chromium

# App code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Entrypoint
CMD ["lambda_function.lambda_handler"]
