# DoGO Backend

Django REST Framework backend for DoGO/SafaApp delivery flows: users, JWT auth, shipments, multi-stop routes, containers, payments, FCM notifications and carrier stats.

## Requirements

- Python 3.11+
- PostgreSQL
- Redis only when `CHANNEL_BACKEND=redis`

## Setup

```bash
cd DoGO
python -m venv .venv
source .venv/bin/activate
pip install -r req.txt
cp .env.example .env
```

Edit `.env`. Do not commit real secrets. For production set `DJANGO_DEBUG=0`, a strong `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS`, Firebase service account path, and provider keys.

For PythonAnywhere use [deploy/PYTHONANYWHERE.md](deploy/PYTHONANYWHERE.md). The backend accepts `DATABASE_URL` for production database configuration.

## Database

```bash
createdb dogo
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

Docker users can start PostgreSQL from `docker/docker-compose.yml` if preferred.

## Main API

- `POST /api/users/register/` registration with `phone_number`, `first_name`, `role`, `password`, `password_confirm`.
- `POST /api/users/token/` JWT login with `phone_number` and `password`.
- `POST /api/users/token/refresh/` JWT refresh.
- `GET /api/users/profile/` current profile.
- `GET /api/delivery/containers/` active containers, supports `bazar_id`, `passage_id`, `q`, `min_lat`, `max_lat`, `min_lon`, `max_lon`.
- `POST /api/delivery/shipments/` create shipment with `service_type` (`amanat`, `cars`, `delivery`) and ordered `stops`.
- `POST /api/delivery/shipments/{id}/accept/` carrier accepts a pending shipment under row lock.
- `POST /api/delivery/shipments/{id}/set_status/` guarded status changes.
- `POST /api/delivery/shipments/{id}/advance/` assigned carrier advances route.

## Admin

Admins can manage bazaars, passages, containers and shipments in Django Admin. Containers are unique by `(passage, number)` and show/search coordinates, number, passage and bazar.

## Tests

```bash
pytest
```

Known external dependencies: reverse geocoding needs `YANDEX_API_KEY`, WhatsApp OTP needs ChatFlow env values, FCM needs a service account file, payments need Finik settings.
