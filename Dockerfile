FROM public.ecr.aws/lambda/python:3.12

# Vendor exact, compatible wheels into /var/task/vendor
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

# Your handler
COPY lambda_function.py /var/task/

# Run
CMD ["lambda_function.lambda_handler"]
