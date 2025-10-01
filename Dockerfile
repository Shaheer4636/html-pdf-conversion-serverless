# Playwright’s official Python image with Chromium + deps
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Common fonts (optional)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    fonts-dejavu-core fonts-dejavu-extra fonts-liberation fonts-noto-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /var/task

# Lambda runtime interface client + app deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY lambda_function.py .

# Headless caches to /tmp; browsers are already in /ms-playwright
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    FONTCONFIG_PATH=/etc/fonts

# Lambda entrypoint
CMD ["python", "-m", "awslambdaric", "lambda_function.lambda_handler"]
