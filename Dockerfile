# AL2023 base (works with Playwright)
FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y at-spi2-atk libXcomposite libXcursor libXdamage libXext libXi \
    libXrandr libXrender libXScrnSaver libXtst pango gtk3 nss \
    dejavu-sans-fonts dejavu-serif-fonts dejavu-sans-mono-fonts \
 && dnf clean all

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN python -m playwright install chromium

# Copy your handler file into /var/task (Lambda’s working dir)
COPY lambda_function.py .    # <— must exist next to Dockerfile

CMD ["index.handler"]
