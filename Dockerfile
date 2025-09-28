FROM public.ecr.aws/lambda/python:3.12

# System libs WeasyPrint needs (AL2023 uses dnf)
RUN dnf install -y \
      cairo cairo-gobject pango gdk-pixbuf2 \
      libjpeg-turbo libpng zlib \
      fontconfig freetype harfbuzz fribidi \
      libxml2 libxslt tzdata \
      dejavu-sans-fonts dejavu-serif-fonts \
  && dnf clean all

# Writable caches for fontconfig/Pango
ENV XDG_CACHE_HOME=/tmp
ENV HOME=/tmp

# Pin versions that are known to work together
# (WeasyPrint 61.x needs pydyf < 0.11; we use 0.10.0)
RUN pip install --no-cache-dir -t /var/task/vendor \
      weasyprint==61.2 \
      pydyf==0.10.0 \
      tinycss2==1.3.0 \
      cssselect2==0.7.0 \
      html5lib==1.1 \
      fonttools==4.53.0 \
      Pillow==10.3.0 \
      Pyphen==0.14.0 \
      cffi==1.16.0

# Your handler
COPY lambda_function.py /var/task/lambda_function.py

# Lambda entrypoint
CMD ["lambda_function.lambda_handler"]
