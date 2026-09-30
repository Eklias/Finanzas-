"""
ASGI config for contabilidad project.
"""
import os
from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contabilidad.settings')
application = get_asgi_application()
#a