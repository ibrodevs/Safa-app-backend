# PythonAnywhere Deployment

Official PythonAnywhere flow for an existing Django project is: upload/clone code, create a virtualenv, install requirements, create a Web app manually, point WSGI at the Django app, configure static/media mappings, then run migrations and reload the Web app.

## Demo Target

- PythonAnywhere username/domain: `safabackend21`
- API base URL for Flutter: `https://safabackend21.pythonanywhere.com/api/`
- Demo database: SQLite via `DJANGO_USE_SQLITE=1`

SQLite is okay for a short demo, but it is not recommended for production traffic. Move to Postgres/external DB before launch.

## Files

- `deploy/pythonanywhere_wsgi.py` is ready for `/home/safabackend21/DoGO`.
- `deploy/pythonanywhere.env.example` is the demo `.env` template.
- `.env.example` lists all general environment variables.

## Commands on PythonAnywhere Bash

```bash
cd ~
git clone <repo-url> DoGO
cd DoGO
python3.13 -m venv .venv
source .venv/bin/activate
pip install -r req.txt
cp deploy/pythonanywhere.env.example .env
```

Generate a real secret and put it into `.env`:

```bash
python - <<'PY'
from django.core.management.utils import get_random_secret_key
print(get_random_secret_key())
PY
```

Minimum `.env` values:

```env
DJANGO_DEBUG=0
DJANGO_SECRET_KEY=<strong-secret>
DJANGO_ALLOWED_HOSTS=safabackend21.pythonanywhere.com
DJANGO_USE_SQLITE=1
DJANGO_SECURE_SSL_REDIRECT=1
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1
```

Then:

```bash
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
python manage.py check
```

## Web Tab

- Source code: `/home/safabackend21/DoGO`
- Virtualenv: `/home/safabackend21/DoGO/.venv`
- WSGI file: copy `deploy/pythonanywhere_wsgi.py`.
- Static files:
  - URL `/static/` -> `/home/safabackend21/DoGO/static_root`
  - URL `/media/` -> `/home/safabackend21/DoGO/media`

After reload, check:

```text
https://safabackend21.pythonanywhere.com/
https://safabackend21.pythonanywhere.com/swagger/
https://safabackend21.pythonanywhere.com/admin/
```

Reload the Web app after every deploy.

## Limitations

PythonAnywhere Web apps are WSGI. REST API and admin work through WSGI. Django Channels/WebSocket realtime parts will not run as ordinary WebSocket service there; keep `CHANNEL_BACKEND=memory` for REST-only deploy or host ASGI/WebSockets somewhere else later.
