FROM public.ecr.aws/lambda/python:3.12

# --- Native deps needed by Chromium/Playwright on AL2023 ---
RUN dnf -y install \
      # X / input / window
      libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst \
      libXrandr libXScrnSaver libXfixes libXrender libxcb \
      # keyboard libs (Ubuntu libxkbcommon0)
      libxkbcommon libxkbcommon-x11 \
      # accessibility (Ubuntu: libatk1.0-0 libatk-bridge2.0-0 libatspi2.0-0)
      atk at-spi2-atk at-spi2-core \
      # graphics / fonts / text
      cairo cairo-gobject pango gdk-pixbuf2 \
      fontconfig freetype harfbuzz fribidi \
      # sound + security + misc
      alsa-lib nspr nss cups-libs dbus-libs \
      # GPU/headless bits
      libdrm libgbm mesa-libgbm \
      # useful utilities & fonts
      which tar unzip findutils shadow-utils \
      dejavu-sans-fonts dejavu-serif-fonts dejavu-sans-mono-fonts \
      google-noto-sans-fonts google-noto-emoji-color-fonts \
    && dnf clean all

# --- Python deps ---
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# --- Download Chromium only (no --with-deps on AL2023) ---
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    HOME=/tmp \
    XDG_CACHE_HOME=/tmp/.cache
RUN mkdir -p /ms-playwright /tmp/.cache/fontconfig && chmod -R 777 /ms-playwright /tmp
RUN python -m playwright install chromium

# --- Function code ---
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.lambda_handler"]
