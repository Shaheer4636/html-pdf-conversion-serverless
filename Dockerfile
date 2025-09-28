FROM public.ecr.aws/lambda/python:3.12

# Install native libs WeasyPrint needs (Amazon Linux 2023 uses microdnf)
# pango pulls in glib2/harfbuzz/fribidi; add cairo and gdk-pixbuf2 explicitly.
RUN microdnf update -y && \
    microdnf install -y \
      pango \
      cairo \
      cairo-gobject \
      gdk-pixbuf2 \
      gdk-pixbuf2-modules \
      libjpeg-turbo \
      libpng \
      freetype \
      fontconfig \
      harfbuzz \
      fribidi \
      libxml2 \
      libxslt \
      libffi \
      tzdata \
      dejavu-sans-fonts \
      dejavu-serif-fonts && \
    microdnf clean all

# (Sanity check at build time; if these files aren't present, fail the build)
RUN test -f /usr/lib64/libpango-1.0.so.0 && \
    test -f /usr/lib64/libcairo.so.2 && \
    test -f /usr/lib64/libgdk_pixbuf-2.0.so.0

# Vendor compatible Python wheels into /var/task/vendor
RUN pip install --no-cache-dir -t /var/task/vendor \
      weasyprint==61.2 \
      pydyf==0.11.0 \
      tinycss2==1.3.0 \
      cssselect2==0.7.0 \
      html5lib==1.1 \
      fonttools==4.53.0 \
      Pillow==10.3.0 \
      Pyphen==0.17.2 \
      cffi==2.0.0

# Your handler (must prepend /var/task/vendor to sys.path)
COPY lambda_function.py /var/task/

# Lambda entrypoint
CMD ["lambda_function.lambda_handler"]
