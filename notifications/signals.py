from django.db.models.signals import post_save, post_delete, m2m_changed
from django.dispatch import receiver
from django.utils import timezone
from messaging.models import (
    Message, MessageReaction, Call, CallParticipant, 
    Conversation, ConversationMember
)
from .models import Notification
from .utils import (
    create_message_notification,
    delete_message_notification,
    create_reaction_notification,
    delete_reaction_notification,
    create_call_notification
)


# ============ MESSAGE NOTIFICATIONS ============

@receiver(post_save, sender=Message)
def handle_new_message_notification(sender, instance, created, **kwargs):
    """
    Create notification for new message (WhatsApp style)
    - Only notify if user is NOT actively in the conversation
    - Notify all conversation members except sender
    """
    if not created:
        return
    
    # Don't notify for deleted messages
    if instance.is_deleted or instance.deleted_for_everyone:
        return
    
    conversation = instance.conversation
    sender_user = instance.sender
    
    # Get all active members except the sender
    members = ConversationMember.objects.filter(
        conversation=conversation,
        left_at__isnull=True
    ).exclude(user=sender_user).select_related('user')
    
    # Determine notification type
    if conversation.type == 'direct':
        notification_type = 'message'
    else:
        notification_type = 'group_message'
    
    # Create notification for each member
    for member in members:
        recipient = member.user
        
        # Check if user is muted
        if member.is_muted:
            continue
        
        # Check if user has blocked the sender
        from messaging.models import BlockedUser
        if BlockedUser.objects.filter(
            blocker=recipient,
            blocked=sender_user
        ).exists():
            continue
        
        # Create the notification
        create_message_notification(
            recipient=recipient,
            sender=sender_user,
            message=instance,
            conversation=conversation,
            notification_type=notification_type
        )


@receiver(post_save, sender=Message)
def handle_message_deletion_notification(sender, instance, created, **kwargs):
    """
    Remove notification when message is deleted for everyone
    """
    if not created and instance.deleted_for_everyone:
        # Delete all notifications for this message
        delete_message_notification(instance)


# ============ MESSAGE REACTION NOTIFICATIONS ============

@receiver(post_save, sender=MessageReaction)
def handle_message_reaction_notification(sender, instance, created, **kwargs):
    """
    Create notification when someone reacts to your message
    - Only notify the message sender
    - Don't notify if you react to your own message
    """
    if not created:
        return
    
    message = instance.message
    reactor = instance.user
    message_sender = message.sender
    
    # Don't notify yourself
    if reactor == message_sender:
        return
    
    # Don't notify if message is deleted
    if message.is_deleted or message.deleted_for_everyone:
        return
    
    # Create reaction notification
    create_reaction_notification(
        recipient=message_sender,
        sender=reactor,
        message=message,
        emoji=instance.emoji
    )


@receiver(post_delete, sender=MessageReaction)
def handle_reaction_removal_notification(sender, instance, **kwargs):
    """
    Remove notification when reaction is removed
    """
    delete_reaction_notification(
        message=instance.message,
        reactor=instance.user
    )


# ============ CALL NOTIFICATIONS ============

@receiver(post_save, sender=Call)
def handle_call_notification(sender, instance, created, **kwargs):
    """
    Create notifications for calls (WhatsApp style)
    - Notify on incoming call
    - Notify on missed call
    """
    if created:
        # Don't create notification on call creation
        # We'll handle it on status changes
        return
    
    # Handle missed calls
    if instance.status == 'missed':
        # Notify all participants who didn't answer
        participants = CallParticipant.objects.filter(
            call=instance,
            status__in=['invited', 'ringing', 'missed']
        ).exclude(user=instance.caller).select_related('user')
        
        for participant in participants:
            create_call_notification(
                recipient=participant.user,
                sender=instance.caller,
                call=instance,
                call_status='missed'
            )
    
    # Handle rejected calls (also counts as missed for caller)
    elif instance.status == 'rejected':
        # Notify caller that call was rejected
        create_call_notification(
            recipient=instance.caller,
            sender=None,  # System notification
            call=instance,
            call_status='rejected'
        )


@receiver(post_save, sender=CallParticipant)
def handle_call_participant_status(sender, instance, created, **kwargs):
    """
    Handle call participant status changes
    """
    if created:
        return
    
    call = instance.call
    participant = instance.user
    
    # If participant missed the call
    if instance.status == 'missed':
        create_call_notification(
            recipient=participant,
            sender=call.caller,
            call=call,
            call_status='missed'
        )


# ============ CONVERSATION NOTIFICATIONS ============

@receiver(post_save, sender=ConversationMember)
def handle_group_member_added(sender, instance, created, **kwargs):
    """
    Notify when someone adds you to a group
    """
    if not created:
        return
    
    conversation = instance.conversation
    
    # Only for group conversations
    if conversation.type != 'group':
        return
    
    # Don't notify if user was the creator
    if instance.user == conversation.created_by:
        return
    
    # Create notification
    Notification.objects.create(
        recipient=instance.user,
        sender=conversation.created_by,
        notification_type='group_added',
        target_type='conversation',
        target_id=conversation.id,
        message=f"{conversation.created_by.username} added you to {conversation.name or 'a group'}",
        payload={
            'conversation_id': str(conversation.id),
            'conversation_name': conversation.name,
            'conversation_type': conversation.type
        }
    )


# ============ REPLY NOTIFICATIONS ============

@receiver(post_save, sender=Message)
def handle_reply_notification(sender, instance, created, **kwargs):
    """
    Create notification when someone replies to your message
    """
    if not created:
        return
    
    # Check if this is a reply
    if not instance.reply_to:
        return
    
    original_message = instance.reply_to
    original_sender = original_message.sender
    replier = instance.sender
    
    # Don't notify if replying to your own message
    if replier == original_sender:
        return
    
    # Don't notify if message is deleted
    if instance.is_deleted or instance.deleted_for_everyone:
        return
    
    # Create reply notification
    Notification.objects.create(
        recipient=original_sender,
        sender=replier,
        notification_type='message_reply',
        target_type='message',
        target_id=instance.id,
        message=f"{replier.username} replied to your message",
        payload={
            'message_id': str(instance.id),
            'conversation_id': str(instance.conversation.id),
            'reply_to_id': str(original_message.id),
            'body': instance.body[:100] if instance.body else ''
        }
    )


# ============ MENTION NOTIFICATIONS (Future) ============

@receiver(post_save, sender=Message)
def handle_mention_notification(sender, instance, created, **kwargs):
    """
    Create notification when someone mentions you in a message
    WhatsApp uses @username mentions
    """
    if not created:
        return
    
    if not instance.body:
        return
    
    # Extract mentions from message body (simple implementation)
    # Look for @username patterns
    import re
    mentions = re.findall(r'@(\w+)', instance.body)
    
    if not mentions:
        return
    
    from django.contrib.auth import get_user_model
    User = get_user_model()
    
    for username in mentions:
        try:
            mentioned_user = User.objects.get(username=username)
            
            # Don't notify if mentioning yourself
            if mentioned_user == instance.sender:
                continue
            
            # Check if mentioned user is in the conversation
            if not instance.conversation.members.filter(
                user=mentioned_user,
                left_at__isnull=True
            ).exists():
                continue
            
            # Create mention notification
            Notification.objects.create(
                recipient=mentioned_user,
                sender=instance.sender,
                notification_type='mention',
                target_type='message',
                target_id=instance.id,
                message=f"{instance.sender.username} mentioned you in a message",
                payload={
                    'message_id': str(instance.id),
                    'conversation_id': str(instance.conversation.id),
                    'body': instance.body[:100] if instance.body else ''
                }
            )
        except User.DoesNotExist:
            continue

