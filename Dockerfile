# Dockerfile
FROM public.ecr.aws/lambda/python:3.12

# Make Playwright use a fixed path that's baked into the image
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# Install Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Install Chromium and all required OS deps into the image
# (This works on Amazon Linux 2023 used by python:3.12 Lambda base)
RUN python -m playwright install --with-deps chromium

# Your function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/

CMD ["lambda_function.lambda_handler"]
