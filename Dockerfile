FROM python:3.12-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash \
    && rm -rf /var/lib/apt/lists/*

COPY api/requirements.txt ./api-requirements.txt
COPY ui/requirements.txt ./ui-requirements.txt
COPY logger/requirements.txt ./logger-requirements.txt
RUN pip install --no-cache-dir -r api-requirements.txt -r ui-requirements.txt -r logger-requirements.txt

COPY api/ ./api/
COPY ui/ ./ui/
COPY assistant/ ./assistant/
COPY logger/ ./logger/
COPY start.sh ./start.sh

ENV API_BASE_URL=http://127.0.0.1:8000
ENV LOG_DIR=/app/logs
ENV LOG_ROOT=/app/logs
ENV TAIL_LINES=300

EXPOSE 8000 8501 8888

CMD ["bash", "start.sh"]
