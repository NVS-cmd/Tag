# Образ берётся через зеркало: Docker Hub из РФ доступен нестабильно. Поменять — в .env (PYTHON_IMAGE)
ARG PYTHON_IMAGE=mirror.gcr.io/library/python:3.12-slim
FROM ${PYTHON_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
RUN chmod +x entrypoint.sh && useradd -m -u 1000 app && chown -R app /app
USER app

EXPOSE 8000
ENTRYPOINT ["./entrypoint.sh"]
