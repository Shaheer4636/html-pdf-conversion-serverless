# Use Amazon Linux 2-based Lambda image (stable with Chrome/Playwright)
FROM public.ecr.aws/lambda/python:3.11

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# System deps for Chromium + fonts (AL2 uses yum)
RUN yum install -y \
      atk at-spi2-atk at-spi2-core gtk3 \
      libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst libXrandr \
      alsa-lib mesa-libgbm nss \
      pango freetype fontconfig \
      dbus-glib \
      xorg-x11-fonts-Type1 xorg-x11-fonts-75dpi xorg-x11-fonts-100dpi xorg-x11-fonts-misc \
  && yum clean all

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Chromium that matches Playwright (pre-bundle into the image)
RUN python -m playwright install --with-deps chromium

# Your code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
CMD ["lambda_function.lambda_handler"]
