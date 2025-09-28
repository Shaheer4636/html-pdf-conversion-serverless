FROM public.ecr.aws/lambda/python:3.12

ENV PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONUNBUFFERED=1

# System libs for WeasyPrint / Cairo / Pango + fonts
RUN dnf install -y \
      cairo pango gdk-pixbuf2 libffi libxml2 libxslt \
      fontconfig freetype libpng libjpeg-turbo \
      xorg-x11-fonts-Type1 xorg-x11-fonts-75dpi \
  && dnf clean all

# Upgrade pip tooling to avoid picking an older wheel from base
RUN python -m pip install --no-cache-dir --upgrade pip setuptools wheel

# Python deps (no cache; pin exact)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Verify at build-time what will be imported at runtime
RUN python - <<'PY'
import sys, inspect
print("=== BUILD VERIFY ===")
print("sys.path =", sys.path)
import weasyprint, pydyf
print("weasyprint", weasyprint.__version__)
print("pydyf", pydyf.__version__)
print("pydyf.PDF.__init__ signature:", inspect.signature(pydyf.PDF.__init__))
PY

# Function code
COPY lambda_function.py ${LAMBDA_TASK_ROOT}/
CMD ["lambda_function.lambda_handler"]
