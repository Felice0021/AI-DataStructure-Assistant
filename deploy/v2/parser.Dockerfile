FROM python:3.12-slim
RUN pip install --no-cache-dir pypdf==6.21.2 python-docx==1.2.0 lxml==6.1.3
COPY parser_child.py /app/backend/v2/parser_child.py
COPY core/errors.py /app/backend/v2/core/errors.py
COPY services/ /app/backend/v2/services/
USER 65534:65534
ENTRYPOINT ["python", "-I", "-B", "/app/backend/v2/parser_child.py"]
