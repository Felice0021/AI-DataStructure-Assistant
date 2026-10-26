FROM python:3.12-slim
RUN pip install --no-cache-dir pypdf==6.21.2 python-docx==1.2.0 lxml==6.1.3
COPY . /app/backend/v2
USER 65534:65534
ENTRYPOINT ["python", "-I", "-B", "/app/backend/v2/parser_child.py"]
