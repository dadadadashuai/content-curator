FROM python:3.11-slim-bookworm

RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg curl && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
    fastapi uvicorn[standard] httpx pydantic apscheduler \
    yt-dlp python-multipart

WORKDIR /app

COPY app/ /app/app/
COPY scripts/ /app/scripts/
COPY cookies.txt /app/cookies.txt
COPY frontend/dist/ /app/static/

RUN mkdir -p /app/data /app/cache

ENV PYTHONPATH=/app
ENV PYTHONUNBUFFERED=1
ENV STATIC_DIR=/app/static

EXPOSE 9100

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "9100"]
