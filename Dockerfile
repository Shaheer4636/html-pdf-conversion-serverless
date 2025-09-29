# Playwright image already includes Chromium + deps + fonts
FROM mcr.microsoft.com/playwright/python:v1.46.0-jammy

# Lambda runtime interface so this image can run on AWS Lambda
RUN pip install --no-cache-dir awslambdaric boto3

# Faster cold start & certs are already present in base image.
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Your Lambda handler code
COPY lambda_function.py /var/task/lambda_function.py

# Lambda entrypoint
CMD ["python", "-m", "awslambdaric", "lambda_function.lambda_handler"]
