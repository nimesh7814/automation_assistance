FROM python:3.12-slim

WORKDIR /app

COPY logger/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY logger/app.py ./app.py

ENV LOG_ROOT=/logs
ENV TAIL_LINES=300

EXPOSE 8888

CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8888"]
