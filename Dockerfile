# AL2023 base (new glibc) – good for Playwright/Chromium
FROM public.ecr.aws/lambda/python:3.12

# System libs + fonts Chromium needs
RUN dnf install -y \
    at-spi2-atk \
    libXcomposite libXcursor libXdamage libXext libXi libXrandr libXrender libXScrnSaver libXtst \
    pango gtk3 nss \
    dejavu-sans-fonts dejavu-serif-fonts dejavu-sans-mono-fonts \
 && dnf clean all

# Work in Lambda's code dir
WORKDIR /var/task

# Python deps
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Playwright browser
RUN python -m playwright install chromium

# --- COPY YOUR HANDLER FILE (don’t use ".") ---
# Your repo shows: lambda_function.py next to Dockerfile
COPY lambda_function.py /var/task/lambda_function.py

# Lambda entrypoint: module.function
CMD ["lambda_function.handler"]
