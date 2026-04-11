import os
from pathlib import Path
from datetime import timedelta
from dotenv import load_dotenv
from decimal import Decimal
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


SECRET_KEY = os.getenv(
    "DJANGO_SECRET_KEY",
    "django-insecure-7dxs7b+%pq5ko2ru*s@z_1=rgm8tlk2k($t0al*w$%b^d^a1b3", 
)

DEBUG = os.getenv("DJANGO_DEBUG", "1") == "1"

ALLOWED_HOSTS = [
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
        'DIRS': [],
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


# DATABASES = {
#     "default": {
#         "ENGINE": "django.db.backends.postgresql",
#         "NAME": os.getenv("POSTGRES_DB", "dogo"),
#         "USER": os.getenv("POSTGRES_USER", "dogo"),
#         "PASSWORD": os.getenv("POSTGRES_PASSWORD", "dogo_pass_123"),
#         "HOST": os.getenv("POSTGRES_HOST", "db"),
#         "PORT": os.getenv("POSTGRES_PORT", "5432"),
#     }
# }



DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}

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

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'
AUTH_USER_MODEL = "users.User"


REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("rest_framework_simplejwt.authentication.JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.AllowAny",),
    "DEFAULT_THROTTLE_CLASSES": [
        "rest_framework.throttling.AnonRateThrottle",
        "rest_framework.throttling.UserRateThrottle",
    ],
    "DEFAULT_THROTTLE_RATES": {"anon": "20/min", "user": "120/min"},
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

CHATFLOW_BASE_URL = os.getenv("CHATFLOW_BASE_URL", "https://app.chatflow.kz")
CHATFLOW_TOKEN = os.getenv("CHATFLOW_TOKEN", "")
CHATFLOW_INSTANCE_ID = os.getenv("CHATFLOW_INSTANCE_ID", "")
OTP_TTL_SECONDS = int(os.getenv("OTP_TTL_SECONDS", "300"))


OSRM_URL = "https://router.project-osrm.org"


FCM_PROJECT_ID = "dogoapp-7b7a2"

FCM_SERVICE_ACCOUNT_FILE = BASE_DIR / "firebase" / "dogoapp-7b7a2-firebase-adminsdk-fbsvc-61e2b5bc29.json"
PLATFORM_COMMISSION_PCT = Decimal("0.10")

FINIK_CURRENCY = os.getenv("FINIK_CURRENCY", "KGS")
FINIK_CALLBACK_URL = os.getenv("FINIK_CALLBACK_URL", "")

DELIVERY_BASE_PRICE = 50
DELIVERY_PER_KM_PRICE = 20
DELIVERY_MIN_FARE = 50
