# Safa backend on DigitalOcean

Production layout:

```text
Internet -> Nginx (HTTPS/WSS) -> 127.0.0.1:8001
                                  -> Daphne / Django ASGI
                                     -> PostgreSQL (private Docker network)
                                     -> Redis Channels layer (private Docker network)
```

The examples use Ubuntu 24.04, domain `api.example.com`, and installation path
`/opt/safa/backend`. Replace both values with the real domain and path.

## 1. Prepare the Droplet

Create a 2 vCPU / 4 GB RAM / 80 GB SSD Ubuntu 24.04 Droplet and add an SSH key.
Point the domain's `A` record to its public IPv4 address before requesting TLS.

```bash
sudo apt update
sudo apt upgrade -y
sudo apt install -y ca-certificates curl git nginx ufw
```

Install Docker from Docker's official Ubuntu repository:

```bash
sudo install -m 0755 -d /etc/apt/keyrings
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc

echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker "$USER"
```

Log out and back in so Docker group membership takes effect, then verify:

```bash
docker --version
docker compose version
```

## 2. Clone and configure

```bash
sudo mkdir -p /opt/safa
sudo chown "$USER":"$USER" /opt/safa
git clone https://github.com/ibrodevs/Safa-app-backend.git /opt/safa/backend
cd /opt/safa/backend
cp .env.example .env
mkdir -p secrets var/static var/media
chmod 700 secrets
```

Generate a Django secret without storing it in shell history:

```bash
docker run --rm python:3.13-slim python -c \
  'import secrets; print(secrets.token_urlsafe(64))'
```

Edit `.env`:

```bash
nano .env
```

At minimum set these production values:

```dotenv
DJANGO_DEBUG=0
ENABLE_DEBUG_OTP_ENDPOINT=0
DJANGO_SECRET_KEY=<generated-secret>
DJANGO_ALLOWED_HOSTS=api.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://api.example.com
DJANGO_USE_SQLITE=0
DJANGO_SECURE_SSL_REDIRECT=1
DJANGO_SESSION_COOKIE_SECURE=1
DJANGO_CSRF_COOKIE_SECURE=1

POSTGRES_DB=safa
POSTGRES_USER=safa
POSTGRES_PASSWORD=<strong-random-password>
POSTGRES_HOST=postgres
POSTGRES_PORT=5432

CHANNEL_BACKEND=redis
REDIS_URL=redis://redis:6379/0
```

Keep `DATABASE_URL` empty when using the individual PostgreSQL variables.
If `DATABASE_URL` is set, Django intentionally gives it priority.

Set the integration values that the application uses:

- Chatflow: `CHATFLOW_TOKEN`, `CHATFLOW_FLOW_ID` and base URL.
- Firebase: Android/iOS project IDs and mounted file paths.
- Finik: account ID, API key, mode, callback URL and currency.
- Yandex: `YANDEX_API_KEY` for geocoding.
- Google Maps: browser/API key used by the map editor if enabled.

Production safety values must remain:

```dotenv
DEMO_OTP_CODE=
STATIC_OTP=
ALLOW_STATIC_OTP_IN_PRODUCTION=0
SAFA_TEST_PRICING=0
SAFA_TEST_PRICE=1
FINIK_TEST_AMOUNT=false
FINIK_CALLBACK_URL=https://api.example.com/api/payments/finik/callback/
```

For a controlled end-to-end Finik test, temporarily set
`SAFA_TEST_PRICING=1` and recreate `web` so Docker reloads `.env`. The API and Finik will use
`SAFA_TEST_PRICE` (normally 1 KGS), while real calculated fares remain stored.
Set `SAFA_TEST_PRICING=0` and recreate `web` to restore real prices.

## 3. Firebase credentials

Download service-account JSON files from the matching Firebase projects and
place them outside Git-tracked source files:

```text
/opt/safa/backend/secrets/firebase-android.json
/opt/safa/backend/secrets/firebase-ios.json
```

```bash
chmod 600 secrets/firebase-android.json secrets/firebase-ios.json
```

The production Compose file mounts `./secrets` read-only at `/run/secrets`.
Use these values in `.env`:

```dotenv
FCM_ANDROID_PROJECT_ID=safa-app-87b24
FCM_ANDROID_SERVICE_ACCOUNT_FILE=/run/secrets/firebase-android.json
FCM_IOS_PROJECT_ID=dogoapp-7b7a2
FCM_IOS_SERVICE_ACCOUNT_FILE=/run/secrets/firebase-ios.json
```

Never commit either JSON. The repository ignores `secrets/*` and
`firebase/*.json`.

## 4. Start the application

Validate and build:

```bash
cd /opt/safa/backend
docker compose -f docker-compose.prod.yml config
docker compose -f docker-compose.prod.yml build web
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml ps
```

The web entrypoint waits for PostgreSQL, applies migrations, runs
`collectstatic --noinput`, and then starts:

```text
daphne -b 0.0.0.0 -p 8001 --proxy-headers core.asgi:application
```

PostgreSQL and Redis have no host port. Daphne is bound only to
`127.0.0.1:8001` on the Droplet.

Create the first administrator after the web service is healthy:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py createsuperuser
```

Useful explicit checks:

```bash
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --check
docker compose -f docker-compose.prod.yml exec web python manage.py check --deploy
curl -H 'Host: api.your-domain.com' -H 'X-Forwarded-Proto: https' \
  http://127.0.0.1:8001/health/
```

## 5. Configure Nginx

Copy the template and replace the example domain if not already done:

```bash
sudo cp deploy/digitalocean/nginx.conf.example /etc/nginx/sites-available/safa
sudo sed -i 's/api\.example\.com/api.your-domain.com/g' \
  /etc/nginx/sites-available/safa
sudo ln -s /etc/nginx/sites-available/safa /etc/nginx/sites-enabled/safa
sudo rm -f /etc/nginx/sites-enabled/default
sudo nginx -t
sudo systemctl reload nginx
```

If the repository is installed elsewhere, also change both `/opt/safa/backend`
static/media aliases in the Nginx file.

The template forwards HTTP and WebSocket Upgrade headers to Daphne and serves:

- `/static/` from `/opt/safa/backend/var/static/`;
- `/media/` from `/opt/safa/backend/var/media/`.

## 6. Firewall and HTTPS

Open SSH before enabling UFW:

```bash
sudo ufw allow OpenSSH
sudo ufw allow 'Nginx Full'
sudo ufw enable
sudo ufw status
```

Do not open ports `5432`, `6379`, or `8001`.

Install Certbot and request a trusted certificate:

```bash
sudo apt install -y certbot python3-certbot-nginx
sudo certbot --nginx -d api.your-domain.com
sudo certbot renew --dry-run
```

After HTTPS works reliably, HSTS can be enabled gradually in `.env`, starting
with a small value such as `DJANGO_SECURE_HSTS_SECONDS=3600`. Do not enable
preload until every subdomain is permanently HTTPS-only.

## 7. Verify production

```bash
curl https://api.your-domain.com/health/
curl https://api.your-domain.com/api/payments/finik/config/
docker compose -f docker-compose.prod.yml exec web \
  python manage.py check_notifications
docker compose -f docker-compose.prod.yml logs --tail=200 web
```

Expected health response:

```json
{"status":"ok","database":"ok"}
```

WebSocket endpoint format is:

```text
wss://api.your-domain.com/ws/shipments/<shipment_id>/?token=<JWT_ACCESS_TOKEN>
```

The JWT user must be the shipment client or assigned specialist. With `wscat`
installed on an administrator workstation, connect and send `{"type":"ping"}`;
the server should answer `{"type":"pong"}`. A 403 for another user is expected.

Before release, complete one real end-to-end flow: WhatsApp OTP, create order,
specialist accepts, WebSocket tracking, work completion, Finik payment, verified
callback, and FCM status notification.

## 8. Logs, restart, and backups

```bash
docker compose -f docker-compose.prod.yml logs -f web
docker compose -f docker-compose.prod.yml logs -f postgres redis
docker compose -f docker-compose.prod.yml restart web
docker compose -f docker-compose.prod.yml ps
```

Create a PostgreSQL backup without exposing the database port:

```bash
mkdir -p backups
docker compose -f docker-compose.prod.yml exec -T postgres \
  sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc' > \
  "backups/safa-$(date +%F-%H%M).dump"
```

The database variables are read from the environment already configured on the
PostgreSQL container. Keep backups outside the Git repository and copy them off
the Droplet regularly. Also back up `var/media/`; Docker volumes preserve
PostgreSQL and Redis across rebuilds, but they are not a replacement for
backups.

## 9. Deploy an update

Review release notes and migrations before updating. Then:

```bash
cd /opt/safa/backend
git pull --ff-only
docker compose -f docker-compose.prod.yml build web
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml exec web python manage.py migrate --noinput
docker compose -f docker-compose.prod.yml exec web \
  python manage.py collectstatic --noinput
docker compose -f docker-compose.prod.yml exec web python manage.py check --deploy
curl https://api.your-domain.com/health/
```

The entrypoint already runs migrations and collectstatic on each web start; the
explicit commands confirm the deployed state and are safe to repeat.

For rollback, check out the previous application revision only after confirming
that its code is compatible with already-applied database migrations. Never
delete Docker volumes as part of a normal rollback or update.
