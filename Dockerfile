# Playwright base with Python + Chromium + all deps preinstalled
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# AWS Lambda Python runtime shim
RUN pip install --no-cache-dir awslambdaric boto3

# Workdir for Lambda
WORKDIR /var/task

# Your Lambda handler
COPY lambda_function.py /var/task/lambda_function.py

# Ensure caches are writable inside Lambda
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    FONTCONFIG_PATH=/etc/fonts

# Start the Lambda runtime
CMD ["python", "-m", "awslambdaric", "lambda_function.lambda_handler"]
