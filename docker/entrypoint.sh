#!/bin/sh

# Wait for postgres (optional, but good practice if using a separate wait-for-it script, 
# for now we rely on depends_on and simple retry or just assuming it's ready quickly enough)

echo "Running migrations..."
python manage.py migrate

echo "Starting server on port 8001..."
python manage.py runserver 0.0.0.0:8001
