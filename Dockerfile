FROM python:3.11-slim

WORKDIR /app

ARG BUILD_VERSION=unknown
ARG BUILD_TIME=unknown
ENV APP_VERSION=$BUILD_VERSION
ENV APP_BUILD_TIME=$BUILD_TIME

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app /app/app
COPY main.py /app/main.py

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]