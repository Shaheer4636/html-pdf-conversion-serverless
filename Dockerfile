FROM public.ecr.aws/lambda/python:3.12

RUN yum install -y \
    libX11 libXcomposite libXcursor libXdamage libXext libXi libXtst \
    pango cups-libs libXrandr alsa-lib atk at-spi2-atk at-spi2-core \
    gtk3 mesa-libgbm nss freetype fontconfig \
    xorg-x11-fonts-Type1 xorg-x11-fonts-75dpi \
  && yum clean all

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium for Playwright inside the image
RUN python -m playwright install --with-deps chromium

# Your handler file
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

# Lambda will call: lambda_function.lambda_handler
CMD ["lambda_function.lambda_handler"]
