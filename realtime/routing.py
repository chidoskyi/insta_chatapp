from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    # User's main chat connection (connects to all conversations)
    re_path(r'ws/chat/$', consumers.ChatConsumer.as_asgi()),
    
    # Notifications
    re_path(r'ws/notifications/$', consumers.NotificationConsumer.as_asgi()),
    
    # Calls
    re_path(r'ws/calls/$', consumers.CallConsumer.as_asgi()),
    
    # Test endpoint for basic WebSocket testing
    re_path(r'ws/test/$', consumers.TestConsumer.as_asgi()),
]