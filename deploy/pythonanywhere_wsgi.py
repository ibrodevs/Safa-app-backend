"""
PythonAnywhere WSGI template for DoGO.

Copy this file's content into the WSGI file from the PythonAnywhere Web tab,
or adapt the paths below to your account/project folder.
"""

import os
import sys
from pathlib import Path

from dotenv import load_dotenv


USERNAME = "safabackend21"
PROJECT_DIR = Path(f"/home/{USERNAME}/DoGO")

if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

load_dotenv(PROJECT_DIR / ".env")

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")

from django.core.wsgi import get_wsgi_application


application = get_wsgi_application()
