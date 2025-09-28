FROM public.ecr.aws/lambda/python:3.12

# Install Chromium and fonts (Amazon Linux 2023 uses dnf)
RUN dnf install -y \
      chromium \
      dejavu-sans-fonts dejavu-serif-fonts liberation-fonts \
      google-noto-sans-fonts google-noto-serif-fonts \
      tzdata \
  && dnf clean all

# Writable caches for fontconfig, etc.
ENV HOME=/tmp
ENV XDG_CACHE_HOME=/tmp

# Keep your existing Python deps minimal (boto3 is in the base image)
COPY lambda_function.py /var/task/lambda_function.py

CMD ["lambda_function.lambda_handler"]
