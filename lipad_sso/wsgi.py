"""
WSGI config for lipad_sso project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/1.7/howto/deployment/wsgi/
"""

import os
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "lipad_sso.settings")

from django.core.wsgi import get_wsgi_application
application = get_wsgi_application()
