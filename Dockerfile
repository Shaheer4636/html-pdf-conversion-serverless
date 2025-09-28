# Lambda base (Amazon Linux 2023, Python 3.12)
FROM public.ecr.aws/lambda/python:3.12

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# System libs for WeasyPrint / Cairo / Pango + fonts
RUN dnf install -y \
      cairo pango gdk-pixbuf2 libffi libxml2 libxslt \
      fontconfig freetype libpng libjpeg-turbo \
      xorg-x11-fonts-Type1 xorg-x11-fonts-75dpi \
  && dnf clean all

# Python deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
CMD ["lambda_function.lambda_handler"]
