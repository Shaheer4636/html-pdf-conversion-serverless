# Playwright’s official Python image (Ubuntu Jammy) – includes Chromium & deps.
FROM mcr.microsoft.com/playwright/python:v1.47.0-jammy

# (Optional) fonts helpful for consistent rendering
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    fonts-dejavu-core fonts-dejavu-extra fonts-liberation fonts-noto-core fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

# Workdir for Lambda code
WORKDIR /var/task

# Lambda runtime interface client + app deps
# (We still install boto3 even though it exists in Lambda to pin behavior inside the container)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# App code
COPY lambda_function.py .

# Helpful envs for headless fonts/cache
ENV HOME=/tmp \
    XDG_CACHE_HOME=/tmp \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Lambda entrypoint (custom runtime via awslambdaric)
CMD ["python", "-m", "awslambdaric", "lambda_function.lambda_handler"]
