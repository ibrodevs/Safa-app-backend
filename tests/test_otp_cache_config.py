"""Verify OTP cache backend selection without contacting a live Redis server."""

import os
import subprocess
import sys


def test_redis_channel_backend_enables_shared_otp_cache():
    env = os.environ.copy()
    env.update(
        DJANGO_DEBUG="1",
        CHANNEL_BACKEND="redis",
        REDIS_URL="redis://127.0.0.1:6379/0",
        OTP_CACHE_REDIS_URL="redis://127.0.0.1:6379/7",
    )
    script = (
        "from core.settings import CACHES; "
        "cache = CACHES['default']; "
        "print(cache['BACKEND'] + '|' + cache['LOCATION'])"
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    assert result.stdout.strip() == (
        "django.core.cache.backends.redis.RedisCache|redis://127.0.0.1:6379/7"
    )
