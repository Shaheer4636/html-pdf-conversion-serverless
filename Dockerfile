FROM public.ecr.aws/lambda/python:3.11
# System deps (fonts optional but recommended)
RUN yum install -y \
    xorg-x11-fonts-Type1 xorg-x11-fonts-misc \
    dejavu-sans-fonts dejavu-serif-fonts dejavu-sans-mono-fonts \
  && yum clean all
# App deps
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Playwright browsers
RUN playwright install --with-deps chromium
# App
COPY . .
CMD ["index.handler"]
