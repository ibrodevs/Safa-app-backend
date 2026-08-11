import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
from decimal import Decimal
import dj_database_url

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"
ENABLE_DEBUG_OTP_ENDPOINT = os.getenv("ENABLE_DEBUG_OTP_ENDPOINT", "0") == "1"

if not DEBUG and not SECRET_KEY:
    raise RuntimeError("DJANGO_SECRET_KEY is required when DJANGO_DEBUG=0")

if not SECRET_KEY:
    SECRET_KEY = "dev-only-change-me"

ALLOWED_HOSTS = [h.strip() for h in os.getenv("DJANGO_ALLOWED_HOSTS", "").split(",") if h.strip()] or [
    "safabackend21.pythonanywhere.com",
    "dordoi-go.tech",
    "www.dordoi-go.tech",
    "164.92.182.171",
    "localhost",
    "127.0.0.1",
]


CSRF_TRUSTED_ORIGINS = [
    f"http://{h.strip()}" for h in ALLOWED_HOSTS if h.strip() and h.strip() != "*"
] + [
    f"https://{h.strip()}" for h in ALLOWED_HOSTS if h.strip() and h.strip() != "*"
]


INSTALLED_APPS = [
    'jazzmin',
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',

    'channels',

    'apps.users',
    'apps.delivery',
    'apps.notification',
    'apps.payments'
]

SECURE_CROSS_ORIGIN_OPENER_POLICY = None
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'core.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

ASGI_APPLICATION = 'core.asgi.application'
WSGI_APPLICATION = 'core.wsgi.application'


DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

if DATABASE_URL:
    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=int(os.getenv("DB_CONN_MAX_AGE", "60")),
        )
    }
elif os.getenv("DJANGO_USE_SQLITE", "0") == "1":
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.postgresql",
            "NAME": os.getenv("POSTGRES_DB", "dogo"),
            "USER": os.getenv("POSTGRES_USER", "dogo"),
            "PASSWORD": os.getenv("POSTGRES_PASSWORD", "dogo_pass_123"),
            "HOST": os.getenv("POSTGRES_HOST", "localhost"),
            "PORT": os.getenv("POSTGRES_PORT", "5432"),
        }
    }



# DATABASES = {
#     'default': {
#         'ENGINE': 'django.db.backends.sqlite3',
#         'NAME': BASE_DIR / 'db.sqlite3',
#     }
# }

CHANNEL_BACKEND = os.getenv("CHANNEL_BACKEND", "memory")  

if CHANNEL_BACKEND == "redis":
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels_redis.core.RedisChannelLayer",
            "CONFIG": {
                "hosts": [os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")],
            },
        }
    }
else:
    CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }


AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'ru'
TIME_ZONE = 'Asia/Bishkek'
USE_I18N = True
USE_TZ = True


STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'static_root'

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

SECURE_SSL_REDIRECT = os.getenv("DJANGO_SECURE_SSL_REDIRECT", "0") == "1"
SESSION_COOKIE_SECURE = os.getenv("DJANGO_SESSION_COOKIE_SECURE", "0") == "1"
CSRF_COOKIE_SECURE = os.getenv("DJANGO_CSRF_COOKIE_SECURE", "0") == "1"
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = "users.User"


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticated",),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "100/min", "user": "1000/min"},
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
}

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(hours=3),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=14),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "AUTH_HEADER_TYPES": ("Bearer",),
}

SPECTACULAR_SETTINGS = {
    "TITLE": "DOGO",
    "DESCRIPTION": "API for DoGo",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": True,
    "SECURITY": [{"Bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}],
}

CHATFLOW_BASE_URL = os.getenv("CHATFLOW_BASE_URL", "https://app.chatflow.kz").strip()
CHATFLOW_TOKEN = os.getenv("CHATFLOW_TOKEN", "").strip()
CHATFLOW_FLOW_ID = os.getenv("CHATFLOW_FLOW_ID", "").strip()
# Only needed by accounts that are still on the legacy lk.chatflow.kz API.
CHATFLOW_INSTANCE_ID = os.getenv("CHATFLOW_INSTANCE_ID", "").strip()
CHATFLOW_TIMEOUT_SECONDS = float(os.getenv("CHATFLOW_TIMEOUT_SECONDS", "15"))
OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))
OTP_MAX_ATTEMPTS = int(os.getenv("OTP_MAX_ATTEMPTS", "5"))
DEMO_OTP_CODE = os.getenv("DEMO_OTP_CODE", "").strip()
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY", "").strip()


OSRM_URL = "https://router.project-osrm.org"


FCM_PROJECT_ID = os.getenv("FCM_PROJECT_ID", "dogoapp-7b7a2")

FCM_SERVICE_ACCOUNT_FILE = os.getenv(
    "FCM_SERVICE_ACCOUNT_FILE",
    str(BASE_DIR / "firebase" / "dogoapp-7b7a2-firebase-adminsdk-fbsvc-61e2b5bc29.json"),
)
PLATFORM_COMMISSION_PCT = Decimal(os.getenv("PLATFORM_COMMISSION_PCT", "0.10"))
SPECIALIST_OFFER_RADIUS_M = int(os.getenv("SPECIALIST_OFFER_RADIUS_M", "2500"))
SPECIALIST_OFFER_MAX_CANDIDATES = int(os.getenv("SPECIALIST_OFFER_MAX_CANDIDATES", "20"))
SPECIALIST_POSITION_STALE_MINUTES = int(os.getenv("SPECIALIST_POSITION_STALE_MINUTES", "30"))

FINIK_CURRENCY = os.getenv("FINIK_CURRENCY", "KGS")
FINIK_ACCOUNT_ID = os.getenv("FINIK_ACCOUNT_ID", "").strip()
FINIK_API_KEY = os.getenv("FINIK_API_KEY", "").strip()
FINIK_BETA = os.getenv("FINIK_BETA", "0").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
FINIK_TIMEOUT_SECONDS = float(os.getenv("FINIK_TIMEOUT_SECONDS", "15"))
FINIK_GRAPHQL_URL = os.getenv("FINIK_GRAPHQL_URL", "").strip()
_FINIK_TEST_AMOUNT_RAW = os.getenv("FINIK_TEST_AMOUNT", "false").strip().lower()
if _FINIK_TEST_AMOUNT_RAW in {"", "0", "false", "no", "off"}:
    FINIK_TEST_AMOUNT = None
else:
    FINIK_TEST_AMOUNT = int(_FINIK_TEST_AMOUNT_RAW)
    if FINIK_TEST_AMOUNT <= 0:
        raise ValueError("FINIK_TEST_AMOUNT must be a positive integer or false")
# Optional override. When empty, the API derives the public callback URL from
# the incoming request (including SECURE_PROXY_SSL_HEADER behind a proxy).
FINIK_CALLBACK_URL = os.getenv("FINIK_CALLBACK_URL", "").strip()

STATIC_OTP = dict(
    item.split(":", 1)
    for item in os.getenv("STATIC_OTP", "").split(",")
    if ":" in item
)
