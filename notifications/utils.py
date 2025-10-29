from django.contrib.auth import get_user_model
from .models import Notification, NotificationPreference, NotificationGroup
from .tasks import send_notification_email, send_push_notification

User = get_user_model()


def create_notification(recipient, sender, notification_type, message='', target_type='', target_id=None, payload=None):
    """
    Create a notification
    
    Args:
        recipient: User object who receives the notification
        sender: User object who triggered the notification
        notification_type: Type of notification (like_post, comment, etc.)
        message: Optional custom message
        target_type: Type of target (post, comment, story, etc.)
        target_id: ID of the target object
        payload: Additional JSON data
    
    Returns:
        Notification object
    """
    # Don't notify yourself
    if recipient == sender:
        return None
    
    # Check if user wants this type of notification
    try:
        preferences = NotificationPreference.objects.get(user=recipient)
        if not preferences.should_notify(notification_type):
            return None
    except NotificationPreference.DoesNotExist:
        pass  # Default to sending notification
    
    # Generate message if not provided
    if not message:
        message = generate_notification_message(sender, notification_type, target_type)
    
    # Create notification
    notification = Notification.objects.create(
        recipient=recipient,
        sender=sender,
        notification_type=notification_type,
        target_type=target_type,
        target_id=target_id,
        message=message,
        payload=payload or {}
    )
    
    # Send email notification if preference is set
    try:
        preferences = NotificationPreference.objects.get(user=recipient)
        should_email = {
            'like_post': preferences.email_on_like,
            'like_comment': preferences.email_on_like,
            'comment': preferences.email_on_comment,
            'reply': preferences.email_on_comment,
            'follow': preferences.email_on_follow,
            'mention': preferences.email_on_mention,
        }.get(notification_type, False)
        
        if should_email:
            send_notification_email.delay(notification.id)
        
        # Send push notification if preference is set
        should_push = {
            'like_post': preferences.push_on_like,
            'like_comment': preferences.push_on_like,
            'comment': preferences.push_on_comment,
            'reply': preferences.push_on_comment,
            'follow': preferences.push_on_follow,
            'mention': preferences.push_on_mention,
            'story_view': preferences.push_on_story_view,
        }.get(notification_type, False)
        
        if should_push:
            send_push_notification.delay(notification.id)
    
    except NotificationPreference.DoesNotExist:
        pass
    
    return notification


def create_grouped_notification(recipient, sender, notification_type, target_type, target_id):
    """
    Create or update a grouped notification
    
    Args:
        recipient: User who receives the notification
        sender: User who triggered the notification
        notification_type: Type of notification
        target_type: Type of target object
        target_id: ID of target object
    
    Returns:
        NotificationGroup object
    """
    # Don't notify yourself
    if recipient == sender:
        return None
    
    # Get or create notification group
    group, created = NotificationGroup.objects.get_or_create(
        recipient=recipient,
        notification_type=notification_type,
        target_type=target_type,
        target_id=target_id,
        defaults={'count': 0}
    )
    
    # Add sender if not already in group
    if not group.senders.filter(id=sender.id).exists():
        group.senders.add(sender)
        group.count = group.senders.count()
        group.is_read = False
        group.save(update_fields=['count', 'is_read'])
    
    return group


def generate_notification_message(sender, notification_type, target_type=''):
    """Generate a notification message"""
    username = sender.username
    
    messages = {
        'like_post': f"{username} liked your post",
        'like_comment': f"{username} liked your comment",
        'comment': f"{username} commented on your post",
        'reply': f"{username} replied to your comment",
        'follow': f"{username} started following you",
        'mention': f"{username} mentioned you in a {target_type}",
        'story_view': f"{username} viewed your story",
        'post_tag': f"{username} tagged you in a post",
    }
    
    return messages.get(notification_type, f"{username} interacted with your content")


def notify_post_like(post, liker):
    """Create notification for post like"""
    if post.user != liker:
        return create_notification(
            recipient=post.user,
            sender=liker,
            notification_type='like_post',
            target_type='post',
            target_id=post.id,
            payload={'post_id': post.id}
        )


def notify_comment_like(comment, liker):
    """Create notification for comment like"""
    if comment.user != liker:
        return create_notification(
            recipient=comment.user,
            sender=liker,
            notification_type='like_comment',
            target_type='comment',
            target_id=comment.id,
            payload={'comment_id': comment.id, 'post_id': comment.post.id}
        )


def notify_comment(post, commenter, comment):
    """Create notification for new comment"""
    if post.user != commenter:
        return create_notification(
            recipient=post.user,
            sender=commenter,
            notification_type='comment',
            target_type='post',
            target_id=post.id,
            payload={
                'post_id': post.id,
                'comment_id': comment.id,
                'comment_text': comment.body[:100]
            }
        )


def notify_reply(comment, replier, reply):
    """Create notification for comment reply"""
    if comment.user != replier:
        return create_notification(
            recipient=comment.user,
            sender=replier,
            notification_type='reply',
            target_type='comment',
            target_id=comment.id,
            payload={
                'parent_comment_id': comment.id,
                'reply_id': reply.id,
                'post_id': comment.post.id,
                'reply_text': reply.body[:100]
            }
        )


def notify_follow(followee, follower):
    """Create notification for new follower"""
    return create_notification(
        recipient=followee,
        sender=follower,
        notification_type='follow',
        payload={'follower_id': follower.id}
    )


def notify_story_view(story, viewer):
    """Create notification for story view"""
    if story.user != viewer:
        return create_notification(
            recipient=story.user,
            sender=viewer,
            notification_type='story_view',
            target_type='story',
            target_id=story.id,
            payload={'story_id': story.id}
        )


def notify_mention(recipient, sender, target_type, target_id):
    """Create notification for mention"""
    return create_notification(
        recipient=recipient,
        sender=sender,
        notification_type='mention',
        target_type=target_type,
        target_id=target_id,
        payload={
            'mentioned_in': target_type,
            'target_id': target_id
        }
    )


def delete_notification(recipient, notification_type, target_type, target_id, sender=None):
    """
    Delete a notification (e.g., when unliking)
    
    Args:
        recipient: User who received the notification
        notification_type: Type of notification to delete
        target_type: Type of target
        target_id: ID of target
        sender: Optional sender filter
    """
    query = Notification.objects.filter(
        recipient=recipient,
        notification_type=notification_type,
        target_type=target_type,
        target_id=target_id
    )
    
    if sender:
        query = query.filter(sender=sender)
    
    query.delete()


def delete_grouped_notification(recipient, notification_type, target_type, target_id, sender):
    """Remove sender from grouped notification"""
    try:
        group = NotificationGroup.objects.get(
            recipient=recipient,
            notification_type=notification_type,
            target_type=target_type,
            target_id=target_id
        )
        
        group.senders.remove(sender)
        group.count = group.senders.count()
        
        if group.count == 0:
            group.delete()
        else:
            group.save(update_fields=['count'])
    
    except NotificationGroup.DoesNotExist:
        pass