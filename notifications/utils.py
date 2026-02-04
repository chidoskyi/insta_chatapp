from django.contrib.auth import get_user_model
from django.utils import timezone
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync
from .models import Notification, NotificationPreference
from messaging.services.presence_service import presence_service

User = get_user_model()


def create_message_notification(recipient, sender, message, conversation, notification_type):
    """
    Create notification for a new message (WhatsApp style)
    
    Args:
        recipient: User who receives the notification
        sender: User who sent the message
        message: Message object
        conversation: Conversation object
        notification_type: 'message' or 'group_message'
    
    Returns:
        Notification object or None
    """
    # Don't notify yourself
    if recipient == sender:
        return None
    
    # Check if user is actively in the conversation (WhatsApp behavior)
    # If user is online AND has the conversation open, don't notify
    if is_user_active_in_conversation(recipient, conversation):
        return None
    
    # Check notification preferences
    if not should_notify_user(recipient, notification_type):
        return None
    
    # Generate message preview
    message_preview = generate_message_preview(message)
    
    # Create notification message
    if conversation.type == 'direct':
        notif_message = f"{sender.username}: {message_preview}"
    else:
        # Group message format: "Group Name\nSender: Message"
        group_name = conversation.name or "Group"
        notif_message = f"{sender.username} in {group_name}: {message_preview}"
    
    # Create notification
    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        notification_type=notification_type,
        target_type='message',
        target_id=message.id,
        message=notif_message,
        payload={
            'message_id': str(message.id),
            'conversation_id': str(conversation.id),
            'conversation_type': conversation.type,
            'conversation_name': conversation.name,
            'message_type': message.message_type,
            'body': message.body[:100] if message.body else '',
            'has_media': bool(message.media),
        }
    )
    
    # Send real-time notification via WebSocket
    send_realtime_notification(recipient, notification)
    
    # Send push notification (if user is offline)
    if not presence_service.is_user_online(str(recipient.id)):
        send_push_notification_async(notification.id)
    
    return notification


def create_reaction_notification(recipient, sender, message, emoji):
    """
    Create notification for message reaction
    
    Args:
        recipient: Message author (who receives notification)
        sender: User who reacted
        message: Message that was reacted to
        emoji: The emoji used
    """
    # Don't notify yourself
    if recipient == sender:
        return None
    
    # Check notification preferences
    if not should_notify_user(recipient, 'message_reaction'):
        return None
    
    # Check if user is active in conversation
    if is_user_active_in_conversation(recipient, message.conversation):
        return None
    
    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        notification_type='message_reaction',
        target_type='message',
        target_id=message.id,
        message=f"{sender.username} reacted {emoji} to your message",
        payload={
            'message_id': str(message.id),
            'conversation_id': str(message.conversation.id),
            'emoji': emoji,
            'message_preview': message.body[:50] if message.body else ''
        }
    )
    
    # Send real-time notification
    send_realtime_notification(recipient, notification)
    
    return notification


def create_call_notification(recipient, sender, call, call_status):
    """
    Create notification for missed/rejected calls
    
    Args:
        recipient: User who receives notification
        sender: User who initiated the call (or None for system)
        call: Call object
        call_status: 'missed', 'rejected', etc.
    """
    # Don't notify yourself
    if sender and recipient == sender:
        return None
    
    # Generate message based on call status
    if call_status == 'missed':
        if call.call_type == 'video':
            notif_message = f"Missed video call from {sender.username}"
        else:
            notif_message = f"Missed voice call from {sender.username}"
    elif call_status == 'rejected':
        notif_message = f"{recipient.username} declined your call"
    else:
        notif_message = f"Call from {sender.username if sender else 'Unknown'}"
    
    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        notification_type='call_missed' if call_status == 'missed' else 'call_rejected',
        target_type='call',
        target_id=call.id,
        message=notif_message,
        payload={
            'call_id': str(call.id),
            'call_type': call.call_type,
            'call_status': call_status,
            'conversation_id': str(call.conversation.id)
        }
    )
    
    # Send real-time notification
    send_realtime_notification(recipient, notification)
    
    # Always send push for missed calls
    send_push_notification_async(notification.id)
    
    return notification


def delete_message_notification(message):
    """
    Delete notification when message is deleted for everyone
    
    Args:
        message: Message object that was deleted
    """
    Notification.objects.filter(
        target_type='message',
        target_id=message.id
    ).delete()


def delete_reaction_notification(message, reactor):
    """
    Delete notification when reaction is removed
    
    Args:
        message: Message object
        reactor: User who removed the reaction
    """
    Notification.objects.filter(
        notification_type='message_reaction',
        target_type='message',
        target_id=message.id,
        sender=reactor
    ).delete()


# ============ HELPER FUNCTIONS ============

def is_user_active_in_conversation(user, conversation):
    """
    Check if user is actively viewing the conversation
    WhatsApp doesn't send notifications if you're in the chat
    
    This checks:
    1. Is user online?
    2. Has user read recent messages? (last_read_at is very recent)
    
    Args:
        user: User object
        conversation: Conversation object
    
    Returns:
        bool: True if user is actively in the conversation
    """
    from messaging.models import ConversationMember
    
    # Check if user is online
    if not presence_service.is_user_online(str(user.id)):
        return False
    
    # Get user's membership
    try:
        member = ConversationMember.objects.get(
            conversation=conversation,
            user=user,
            left_at__isnull=True
        )
        
        # If user read something in the last 10 seconds, they're active
        if member.last_read_at:
            time_since_read = timezone.now() - member.last_read_at
            if time_since_read.total_seconds() < 10:
                return True
        
        return False
    except ConversationMember.DoesNotExist:
        return False


def should_notify_user(user, notification_type):
    """
    Check if user wants this type of notification based on preferences
    
    Args:
        user: User object
        notification_type: Type of notification
    
    Returns:
        bool: True if user should be notified
    """
    try:
        prefs = NotificationPreference.objects.get(user=user)
        
        # If all notifications are paused, return False
        if prefs.pause_all:
            return False
        
        # Map notification types to preference fields
        type_map = {
            'message': prefs.notify_on_message,
            'group_message': prefs.notify_on_group_message,
            'message_reaction': prefs.notify_on_reaction,
            'message_reply': prefs.notify_on_reply,
            'call_missed': prefs.notify_on_call,
            'mention': prefs.notify_on_mention,
        }
        
        return type_map.get(notification_type, True)
    
    except NotificationPreference.DoesNotExist:
        # Default to sending notifications
        return True


def generate_message_preview(message):
    """
    Generate a preview of the message for notification
    
    Args:
        message: Message object
    
    Returns:
        str: Preview text
    """
    if message.message_type == 'text':
        preview = message.body[:100] if message.body else ''
        return preview if preview else '(Empty message)'
    
    elif message.message_type == 'image':
        return '📷 Photo'
    
    elif message.message_type == 'video':
        return '🎥 Video'
    
    elif message.message_type == 'audio':
        return '🎵 Audio'
    
    elif message.message_type == 'document':
        return '📄 Document'
    
    elif message.message_type == 'location':
        return '📍 Location'
    
    elif message.message_type == 'contact':
        return '👤 Contact'
    
    else:
        return 'Message'


def send_realtime_notification(recipient, notification):
    """
    Send notification via WebSocket to user's NotificationConsumer
    
    Args:
        recipient: User object
        notification: Notification object
    """
    from .serializers import NotificationSerializer
    
    channel_layer = get_channel_layer()
    
    # Serialize notification
    serializer = NotificationSerializer(notification)
    
    # Send to user's notification room
    async_to_sync(channel_layer.group_send)(
        f'notifications_{recipient.id}',
        {
            'type': 'notification_event',
            'data': {
                'type': 'new_notification',
                'notification': serializer.data
            }
        }
    )


def send_push_notification_async(notification_id):
    """
    Queue push notification for async sending
    
    Args:
        notification_id: ID of notification to send
    """
    # Import here to avoid circular imports
    from .tasks import send_push_notification
    
    try:
        send_push_notification.delay(notification_id)
    except Exception as e:
        print(f"Failed to queue push notification: {e}")


def get_unread_notification_count(user):
    """
    Get count of unread notifications for user
    
    Args:
        user: User object
    
    Returns:
        int: Count of unread notifications
    """
    return Notification.objects.filter(
        recipient=user,
        is_read=False
    ).count()


def mark_conversation_notifications_read(user, conversation):
    """
    Mark all notifications for a conversation as read
    WhatsApp does this when you open a chat
    
    Args:
        user: User object
        conversation: Conversation object
    """
    from django.utils import timezone
    
    Notification.objects.filter(
        recipient=user,
        is_read=False,
        payload__conversation_id=str(conversation.id)
    ).update(
        is_read=True,
        read_at=timezone.now()
    )


def clear_old_notifications(days=30):
    """
    Clear read notifications older than X days
    WhatsApp keeps notifications for about 30 days
    
    Args:
        days: Number of days to keep
    """
    from datetime import timedelta
    
    cutoff_date = timezone.now() - timedelta(days=days)
    
    deleted_count = Notification.objects.filter(
        is_read=True,
        read_at__lt=cutoff_date
    ).delete()[0]
    
    return deleted_count


