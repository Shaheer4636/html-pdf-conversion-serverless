FROM public.ecr.aws/lambda/python:3.12

ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONUNBUFFERED=1

# Runtime libs Chromium needs on Amazon Linux 2023
RUN dnf install -y \
    # X stack
    libX11 libXcomposite libXcursor libXdamage libXext libXi libXrandr libXrender libXScrnSaver libXtst libxkbcommon \
    # graphics / EGL
    libdrm mesa-libgbm mesa-libEGL mesa-libGL \
    # rendering / fonts
    pango cairo gdk-pixbuf2 freetype fontconfig \
    # sound (harmless in headless)
    alsa-lib \
    # security & misc
    nss nspr cups-libs dbus-libs expat glib2 zlib libjpeg-turbo libpng \
    # accessibility
    at-spi2-core at-spi2-atk atk \
  && dnf clean all

# (optional) custom fonts can be copied into this folder
RUN mkdir -p /usr/share/fonts/custom && fc-cache -f

# Python deps
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Download Chromium at build time so it’s baked into the image
RUN python -m playwright install chromium

# Lambda handler
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.lambda_handler"]
