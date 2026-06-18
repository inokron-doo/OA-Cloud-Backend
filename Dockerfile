FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# tzdata: the app uses zoneinfo (e.g. ZoneInfo("Europe/Ljubljana")) and APScheduler,
# both of which need the IANA timezone database. slim images don't ship it.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 8080

# Default command runs the API. The compose overrides this for the one-shot
# migration container (`alembic upgrade head`) and the iot-ingest worker
# (`python scripts/iot_ingest.py`), which share this same image.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
