FROM public.ecr.aws/lambda/python:3.12

RUN dnf install -y \
      cairo cairo-gobject pango gdk-pixbuf2 \
      libjpeg-turbo libpng zlib \
      fontconfig freetype harfbuzz fribidi \
      libxml2 libxslt tzdata \
      dejavu-sans-fonts dejavu-serif-fonts \
  && dnf clean all

ENV XDG_CACHE_HOME=/tmp \
    HOME=/tmp

RUN test -f /usr/lib64/libpango-1.0.so.0 && \
    test -f /usr/lib64/libcairo.so.2 && \
    test -f /usr/lib64/libgdk_pixbuf-2.0.so.0

COPY requirements-vendor.txt /var/task/requirements-vendor.txt
RUN pip install --no-cache-dir -r /var/task/requirements-vendor.txt -t /var/task/vendor

COPY lambda_function.py /var/task/lambda_function.py
CMD ["lambda_function.lambda_handler"]
