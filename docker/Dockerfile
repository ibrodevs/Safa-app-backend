FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DJANGO_SETTINGS_MODULE=core.settings

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Run as non-root to limit blast radius of any RCE vulnerability.
RUN adduser --disabled-password --no-create-home --gecos "" appuser

COPY req.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r req.txt

COPY . .

RUN chmod +x /app/docker/entrypoint.sh \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8001

ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
# Gunicorn managing Uvicorn workers: 4 workers with automatic recycling
# to prevent memory leaks, and proper timeout handling.
CMD ["gunicorn", "core.asgi:application", \
     "-k", "uvicorn.workers.UvicornWorker", \
     "-w", "4", \
     "--bind", "0.0.0.0:8001", \
     "--max-requests", "5000", \
     "--max-requests-jitter", "500", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--forwarded-allow-ips", "*"]
