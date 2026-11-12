"""Production WSGI entry point: gunicorn wsgi:app."""

from app import app

__all__ = ('app',)
