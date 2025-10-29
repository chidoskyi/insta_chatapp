from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync


def send_notification_ws(user_id, notification_data):
    """
    Send notification via WebSocket
    
    Args:
        user_id: ID of the user to send notification to
        notification_data: Dictionary with notification data
    """
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f'notifications_{user_id}',
        {
            'type': 'notification_event',
            'data': notification_data
        }
    )


def send_post_like_ws(post_id, liker_data, action='like'):
    """
    Send post like/unlike event via WebSocket
    
    Args:
        post_id: ID of the post
        liker_data: Dictionary with liker info
        action: 'like' or 'unlike'
    """
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f'post_{post_id}',
        {
            'type': 'post_like',
            'data': {
                'action': action,
                'user': liker_data,
                'post_id': post_id
            }
        }
    )


def send_post_comment_ws(post_id, comment_data):
    """
    Send new comment event via WebSocket
    
    Args:
        post_id: ID of the post
        comment_data: Dictionary with comment data
    """
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f'post_{post_id}',
        {
            'type': 'post_comment',
            'data': comment_data
        }
    )


def send_message_ws(conversation_id, message_data):
    """
    Send new message via WebSocket
    
    Args:
        conversation_id: ID of the conversation
        message_data: Dictionary with message data
    """
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f'chat_{conversation_id}',
        {
            'type': 'chat_message',
            'message': message_data
        }
    )


def send_typing_indicator_ws(conversation_id, user_data, is_typing=True):
    """
    Send typing indicator via WebSocket
    
    Args:
        conversation_id: ID of the conversation
        user_data: Dictionary with user info
        is_typing: Boolean indicating typing status
    """
    channel_layer = get_channel_layer()
    
    async_to_sync(channel_layer.group_send)(
        f'chat_{conversation_id}',
        {
            'type': 'typing_indicator',
            'user_id': user_data['id'],
            'username': user_data['username'],
            'is_typing': is_typing
        }
    )