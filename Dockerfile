# Simple, reliable: Ubuntu + wkhtmltopdf + Python + Lambda RIC
FROM ubuntu:22.04

# System deps (wkhtmltopdf + fonts + python)
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
    wkhtmltopdf \
    python3 python3-pip \
    ca-certificates fontconfig \
    fonts-dejavu-core fonts-dejavu-extra fonts-liberation fonts-noto-core fonts-noto-color-emoji \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /var/task

# Python deps into /var/task (Lambda looks here)
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt -t .

# App
COPY lambda_function.py .

# Lambda runs fine as long as we launch the RIC
ENV HOME=/tmp XDG_CACHE_HOME=/tmp
CMD ["python3", "-m", "awslambdaric", "lambda_function.lambda_handler"]
