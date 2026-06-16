FROM python:3.12-slim

WORKDIR /app

COPY ui/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY ui/ ./

EXPOSE 8501

CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.maxUploadSize=200", "--server.headless=true"]
