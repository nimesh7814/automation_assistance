FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./api-requirements.txt
COPY ui/requirements.txt ./ui-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt -r ui-requirements.txt

COPY api/ ./api/
COPY ui/ ./ui/
COPY assistant/ ./assistant/
COPY start.sh ./start.sh

ENV API_BASE_URL=http://127.0.0.1:8000
ENV LOG_DIR=/app/logs

EXPOSE 8000 8501

CMD ["bash", "start.sh"]
