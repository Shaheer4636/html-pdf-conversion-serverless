# Ubuntu 22.04 + Python + Playwright + browsers preinstalled
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# Install Lambda Runtime Interface Client + boto3 for S3
RUN pip install --no-cache-dir awslambdaric boto3

# Workdir for Lambda code
WORKDIR /var/task

# Copy your Lambda handler
COPY lambda_function.py /var/task/lambda_function.py

# Make font caches writable at runtime
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    FONTCONFIG_PATH=/etc/fonts \
    FONTCONFIG_FILE=/etc/fonts/fonts.conf

# Launch Lambda runtime against our handler
CMD ["python", "-m", "awslambdaric", "lambda_function.lambda_handler"]
