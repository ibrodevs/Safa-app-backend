#!/bin/sh
set -eu

if [ "${DJANGO_USE_SQLITE:-0}" != "1" ]; then
    postgres_host="${POSTGRES_HOST:-postgres}"
    postgres_port="${POSTGRES_PORT:-5432}"
    postgres_user="${POSTGRES_USER:?POSTGRES_USER is required}"

    echo "Waiting for PostgreSQL at ${postgres_host}:${postgres_port}..."
    until pg_isready -h "$postgres_host" -p "$postgres_port" -U "$postgres_user" >/dev/null 2>&1; do
        sleep 2
    done
fi

mkdir -p /app/static_root /app/media

echo "Applying database migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

echo "Starting ASGI server..."
exec "$@"
