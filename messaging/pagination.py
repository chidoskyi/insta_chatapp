# messaging/pagination.py
from rest_framework.pagination import CursorPagination

class CustomCursorPagination(CursorPagination):
    """
    Custom cursor pagination for conversations
    - Ordered by most recent first
    - Page size of 20 items
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = '-created_at'  # Most recent first
    cursor_query_param = 'cursor'


class MessageCursorPagination(CursorPagination):
    """
    Cursor pagination specifically for messages
    - Ordered by oldest first (chronological for chat display)
    - Page size of 20 items
    """
    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 100
    ordering = 'created_at'  # ← Oldest first for messages
    cursor_query_param = 'cursor'