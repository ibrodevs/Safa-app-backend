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

COPY req.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r req.txt

COPY . .

RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
CMD ["daphne", "-b", "0.0.0.0", "-p", "8001", "--proxy-headers", "core.asgi:application"]
