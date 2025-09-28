FROM public.ecr.aws/lambda/python:3.12

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# Amazon Linux 2023 uses dnf; install Chromium deps + fonts
RUN dnf install -y \
      at-spi2-atk at-spi2-core atk \
      cups-libs gtk3 \
      libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst libXrandr \
      alsa-lib mesa-libgbm nss \
      pango freetype fontconfig libuuid \
      dejavu-sans-fonts dejavu-serif-fonts liberation-fonts \
  && dnf clean all

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Chromium into the image
RUN python -m playwright install chromium

COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
CMD ["lambda_function.lambda_handler"]
