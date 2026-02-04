# instachat_backend/asgi.py
import os
import django
from django.core.asgi import get_asgi_application

# Set Django settings module BEFORE importing anything that might use Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'instachat_backend.settings')

# Initialize Django
django.setup()

# NOW import other modules that use Django
from channels.routing import ProtocolTypeRouter, URLRouter
from realtime.middleware import JWTAuthMiddleware

# Import routing after Django is setup
import realtime.routing

application = ProtocolTypeRouter({
    "http": get_asgi_application(),
    "websocket": JWTAuthMiddleware(
        URLRouter(
            realtime.routing.websocket_urlpatterns
        )
    ),
})