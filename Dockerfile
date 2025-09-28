# Lambda Python base image
FROM public.ecr.aws/lambda/python:3.12

# Copy and install vendored wheels into /var/task/vendor
COPY requirements-vendor.txt /var/task/requirements-vendor.txt
RUN pip install --no-cache-dir -r /var/task/requirements-vendor.txt -t /var/task/vendor

# Your handler code
COPY lambda_function.py /var/task/



# Entrypoint
CMD ["lambda_function.lambda_handler"]
