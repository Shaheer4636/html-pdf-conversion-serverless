FROM public.ecr.aws/lambda/python:3.12

# System libs needed by Chromium for PDF
RUN dnf install -y \
    cairo cairo-gobject pango gdk-pixbuf2 \
    libjpeg-turbo libpng zlib \
    fontconfig freetype harfbuzz fribidi \
    libxml2 libxslt \
  && dnf clean all && rm -rf /var/cache/dnf

# Python deps
COPY requirements.txt /var/task/requirements.txt
RUN pip install --no-cache-dir -r /var/task/requirements.txt

# Install chromium once at build-time
RUN python -m playwright install chromium

# Writable font cache
ENV XDG_CACHE_HOME=/tmp/fontcache
RUN mkdir -p /tmp/fontcache && chmod 777 /tmp/fontcache

# App code
COPY lambda_function.py /var/task/

CMD ["lambda_function.lambda_handler"]
