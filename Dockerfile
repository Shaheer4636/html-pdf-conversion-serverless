# Dockerfile
FROM public.ecr.aws/lambda/python:3.12

# AL2023 uses dnf (not yum)
RUN dnf install -y \
      at-spi2-atk at-spi2-core atk \
      cups-libs gtk3 \
      libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst libXrandr \
      alsa-lib mesa-libgbm nss \
      pango freetype fontconfig \
      dejavu-sans-fonts dejavu-serif-fonts \
  && dnf clean all

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Fetch the Chromium binary Playwr
RUN python -m playwright install chromium

COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
CMD ["lambda_function.lambda_handler"]
