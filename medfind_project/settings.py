"""
Django settings for the MedFind project.
"""

from pathlib import Path
from decouple import config

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent

# SECURITY WARNING: keep the secret key used in production secret!
# this portion checks the secret key aka the database you use. 
SECRET_KEY = config('DJANGO_SECRET_KEY', default='django-insecure-change-this-key-later')

# SECURITY WARNING: don't run with debug turned on in production!
DEBUG = config('DJANGO_DEBUG', default=True, cast=bool)

ALLOWED_HOSTS = ['*']  # tighten this once you deploy


# Application definition

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # MedFind apps — one Django app per area of the system
    'landing_app',    # public landing page (no models)
    'login_app',      # login screen (no models)
    'register_app',   # registration screens + seed/admin commands (no models)
    'home_app',       # user home/search + User, Medicine_Category, Medicine, Favorite, Search_history
    'pharmacy_app',   # pharmacy portal + Pharmacy, Inventory, Operating_hours, Pharmacy_verification
    'admin_app',      # admin portal + Admin, Activity_Log
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'medfind_project.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],  # project-level templates (optional)
        'APP_DIRS': True,  # lets Django find accounts/templates/... automatically
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'medfind_project.session_auth.account_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'medfind_project.wsgi.application'


# Database
# MedFind stores its data (users, pharmacies, medicines, etc.) in a
# Supabase-hosted Postgres database. Fill in your real credentials in a
# ".env" file (copy .env.example -> .env) once you've created your
# Supabase project.

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': config('SUPABASE_DB_NAME', default='postgres'),
        'USER': config('SUPABASE_DB_USER', default='postgres'),
        'PASSWORD': config('SUPABASE_DB_PASSWORD', default=''),
        'HOST': config('SUPABASE_DB_HOST', default=''),
        'PORT': config('SUPABASE_DB_PORT', default='5432'),
        # Supabase only accepts SSL connections.
        'OPTIONS': {'sslmode': config('SUPABASE_DB_SSLMODE', default='require')},
        # Set SUPABASE_USE_POOLER=True if you use the transaction pooler (port 6543).
        'DISABLE_SERVER_SIDE_CURSORS': config('SUPABASE_USE_POOLER', default=False, cast=bool),
    }
}

# Optional: run against a local SQLite file instead of Supabase (handy for
# quick offline testing). Off by default -- leave it off to use Supabase.
if config('DJANGO_USE_SQLITE', default=False, cast=bool):
    DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]


# Internationalization

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True


# Static files (CSS, JavaScript, Images)

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# --- Uploaded files (pharmacy verification documents) ---
MEDIA_URL = 'media/'
MEDIA_ROOT = BASE_DIR / 'media'

# --- Auth ---
# MedFind does not use django.contrib.auth.User for its accounts. Users,
# pharmacies and admins live in their own ERD tables and log in through
# medfind_project/session_auth.py. (django.contrib.auth is still installed
# only so the built-in /admin/ site keeps working for a Django superuser.)
