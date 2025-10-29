from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta


@shared_task
def send_notification_email(notification_id):
    """Send email notification"""
    from .models import Notification
    
    try:
        notification = Notification.objects.select_related('recipient', 'sender').get(id=notification_id)
        
        subject = f"New notification from {notification.sender.username if notification.sender else 'Instagram'}"
        message = notification.message
        recipient_email = notification.recipient.email
        
        # Send email (configure EMAIL settings in Django settings)
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@instagram.com',
            recipient_list=[recipient_email],
            fail_silently=True,
        )
        
        return f"Email sent to {recipient_email}"
    
    except Notification.DoesNotExist:
        return f"Notification {notification_id} not found"
    except Exception as e:
        return f"Error sending email: {str(e)}"


@shared_task
def send_push_notification(notification_id):
    """Send push notification (placeholder for mobile app)"""
    from .models import Notification
    
    try:
        notification = Notification.objects.select_related('recipient', 'sender').get(id=notification_id)
        
        # Placeholder for push notification service (FCM, APNs, etc.)
        # In production, you'd integrate with Firebase Cloud Messaging or Apple Push Notification service
        
        payload = {
            'title': 'New Notification',
            'body': notification.message,
            'data': {
                'notification_id': notification.id,
                'type': notification.notification_type,
                'sender_id': notification.sender.id if notification.sender else None,
            }
        }
        
        # Example FCM integration:
        # from firebase_admin import messaging
        # message = messaging.Message(
        #     notification=messaging.Notification(
        #         title=payload['title'],
        #         body=payload['body']
        #     ),
        #     data=payload['data'],
        #     token=notification.recipient.fcm_token  # Store FCM token in user model
        # )
        # response = messaging.send(message)
        
        return f"Push notification prepared for {notification.recipient.username}"
    
    except Notification.DoesNotExist:
        return f"Notification {notification_id} not found"
    except Exception as e:
        return f"Error sending push notification: {str(e)}"


@shared_task
def cleanup_old_notifications():
    """Delete old read notifications (older than 30 days)"""
    from .models import Notification
    
    cutoff_date = timezone.now() - timedelta(days=30)
    
    deleted_count = Notification.objects.filter(
        is_read=True,
        read_at__lt=cutoff_date
    ).delete()[0]
    
    return f"Deleted {deleted_count} old notifications"


@shared_task
def send_notification_digest(user_id):
    """Send daily/weekly notification digest email"""
    from .models import Notification
    from django.contrib.auth import get_user_model
    
    User = get_user_model()
    
    try:
        user = User.objects.get(id=user_id)
        
        # Get unread notifications from last 24 hours
        cutoff = timezone.now() - timedelta(hours=24)
        notifications = Notification.objects.filter(
            recipient=user,
            is_read=False,
            created_at__gte=cutoff
        ).select_related('sender')
        
        if not notifications.exists():
            return f"No unread notifications for {user.username}"
        
        # Build email content
        subject = f"You have {notifications.count()} new notifications"
        
        message_lines = [f"Hi {user.username},\n"]
        message_lines.append(f"You have {notifications.count()} unread notifications:\n")
        
        for notif in notifications[:10]:  # Limit to 10 in digest
            message_lines.append(f"- {notif.message}")
        
        if notifications.count() > 10:
            message_lines.append(f"\n... and {notifications.count() - 10} more")
        
        message = "\n".join(message_lines)
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@instagram.com',
            recipient_list=[user.email],
            fail_silently=True,
        )
        
        return f"Digest email sent to {user.username}"
    
    except User.DoesNotExist:
        return f"User {user_id} not found"
    except Exception as e:
        return f"Error sending digest: {str(e)}"