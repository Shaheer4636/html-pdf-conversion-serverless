FROM public.ecr.aws/lambda/python:3.12

# System libs needed by WeasyPrint (Pango/Cairo stack)
RUN dnf install -y \
      cairo cairo-gobject pango gdk-pixbuf2 \
      libjpeg-turbo libpng zlib \
      fontconfig freetype harfbuzz fribidi \
      libxml2 libxslt && \
    dnf clean all

# Put WeasyPrint caches/fonts in writable /tmp to silence fontconfig warnings
ENV XDG_CACHE_HOME=/tmp \
    HOME=/tmp

# Install Python deps into /var/task/vendor so we control import order
COPY requirements-vendor.txt /var/task/requirements-vendor.txt
RUN pip install --no-cache-dir -r /var/task/requirements-vendor.txt -t /var/task/vendor

# Your handler
COPY lambda_function.py /var/task/lambda_function.py

# Lambda entrypoint
CMD ["lambda_function.lambda_handler"]
