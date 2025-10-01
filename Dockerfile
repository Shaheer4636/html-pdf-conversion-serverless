FROM public.ecr.aws/lambda/python:3.12

# Fonts + X libs + tools needed to unpack the wkhtmltopdf archive
RUN dnf -y update && dnf -y install \
    fontconfig freetype \
    dejavu-sans-fonts dejavu-serif-fonts \
    liberation-sans-fonts liberation-serif-fonts \
    libX11 libXext libXrender libXau libXdmcp \
    tar xz \
 && dnf clean all

# Download a static wkhtmltopdf 0.12.6-1 build and install it
RUN curl -L -o /tmp/wkhtmltox.tar.xz \
      https://github.com/wkhtmltopdf/packaging/releases/download/0.12.6-1/wkhtmltox-0.12.6-1.linux-generic-amd64.tar.xz \
 && mkdir -p /opt/wkhtmltox \
 && tar -xJf /tmp/wkhtmltox.tar.xz -C /opt/wkhtmltox --strip-components=1 \
 && cp /opt/wkhtmltox/bin/wkhtmltopdf /usr/local/bin/wkhtmltopdf \
 && chmod +x /usr/local/bin/wkhtmltopdf \
 && /usr/local/bin/wkhtmltopdf --version

WORKDIR /var/task
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt --target .

COPY lambda_function.py .

ENV HOME=/tmp XDG_CACHE_HOME=/tmp FONTCONFIG_PATH=/etc/fonts

CMD [ "lambda_function.lambda_handler" ]
