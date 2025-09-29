# AL2023 base (glibc 2.34)
FROM public.ecr.aws/lambda/python:3.12

# System libs + fonts required by Chromium
RUN dnf install -y \
    at-spi2-atk \
    libXcomposite libXcursor libXdamage libXext libXi libXrandr libXrender libXScrnSaver libXtst \
    pango gtk3 nss \
    dejavu-sans-fonts dejavu-serif-fonts dejavu-sans-mono-fonts \
 && dnf clean all

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Download Chromium managed by Playwright (no --with-deps on AL2023)
RUN python -m playwright install chromium

# App
COPY . .
# Your handler is `index.handler` (change if needed)
CMD ["index.handler"]
