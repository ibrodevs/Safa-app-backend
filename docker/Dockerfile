FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    DJANGO_SETTINGS_MODULE=core.settings

WORKDIR /app

# postgresql-client нужен для pg_isready в entrypoint.sh
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Устанавливаем зависимости
COPY req.txt .
RUN pip install --no-cache-dir -r req.txt

# Копируем проект
COPY . .

# Права на entrypoint
RUN chmod +x /app/docker/entrypoint.sh

EXPOSE 8001

ENTRYPOINT ["sh", "/app/docker/entrypoint.sh"]
