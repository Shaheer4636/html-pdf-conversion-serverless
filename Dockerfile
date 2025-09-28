FROM public.ecr.aws/lambda/python:3.12

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

RUN dnf install -y \
      cairo pango gdk-pixbuf2 libffi libxml2 libxslt \
      fontconfig freetype libpng libjpeg-turbo \
      xorg-x11-fonts-Type1 xorg-x11-fonts-75dpi \
  && dnf clean all

RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Build-time sanity check
RUN python - <<'PY'
import inspect, weasyprint, pydyf
print("=== BUILD VERIFY ===")
print("weasyprint:", weasyprint.__version__)
print("pydyf:", pydyf.__version__)
print("pydyf.PDF.__init__ signature:", inspect.signature(pydyf.PDF.__init__))
PY

COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
CMD ["lambda_function.lambda_handler"]
