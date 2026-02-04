from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
from .models import Notification
from accounts.models import User
from celery import shared_task

@shared_task
def send_notification_email(notification_id):
    """
    Send email notification
    
    Args:
        notification_id: ID of the notification
    """
    try:
        notification = Notification.objects.get(id=notification_id)
        recipient = notification.recipient
        
        # Check if user has email notifications enabled
        if not hasattr(recipient, 'notification_preferences'):
            return
        
        prefs = recipient.notification_preferences
        
        # Check if email should be sent for this notification type
        type_map = {
            'message': prefs.email_on_message,
            'group_message': prefs.email_on_group_message,
        }
        
        if not type_map.get(notification.notification_type, False):
            return
        
        # Prepare email
        subject = f"New message from {notification.sender.username if notification.sender else 'WhatsApp Clone'}"
        
        # Message body
        if prefs.show_message_preview:
            message = notification.message
        else:
            message = "You have a new message"
        
        # HTML email
        html_message = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #25D366;">WhatsApp Clone</h2>
                    <p>{message}</p>
                    <p>
                        <a href="{settings.FRONTEND_URL}/chat/{notification.conversation_id}" 
                           style="background-color: #25D366; color: white; padding: 10px 20px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            View Message
                        </a>
                    </p>
                    <hr>
                    <p style="color: #666; font-size: 12px;">
                        You're receiving this email because you have email notifications enabled. 
                        <a href="{settings.FRONTEND_URL}/settings/notifications">Change notification settings</a>
                    </p>
                </div>
            </body>
        </html>
        """
        
        # Send email
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[recipient.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        print(f"✅ Email sent to {recipient.email} for notification {notification_id}")
        
    except Notification.DoesNotExist:
        print(f"❌ Notification {notification_id} not found")
    except Exception as e:
        print(f"❌ Failed to send email for notification {notification_id}: {e}")


@shared_task
def send_push_notification(notification_id):
    """
    Send push notification (Firebase Cloud Messaging)
    
    This is a placeholder - you'll need to implement actual FCM integration
    
    Args:
        notification_id: ID of the notification
    """
    try:
        notification = Notification.objects.get(id=notification_id)
        recipient = notification.recipient
        
        # Check if user has push notifications enabled
        if not hasattr(recipient, 'notification_preferences'):
            return
        
        prefs = recipient.notification_preferences
        
        if not prefs.should_send_push(notification.notification_type):
            return
        
        # TODO: Implement Firebase Cloud Messaging (FCM)
        # This requires:
        # 1. User's FCM device token (stored in a separate model)
        # 2. Firebase Admin SDK
        # 3. Proper FCM configuration
        
        # Placeholder implementation
        print(f"📱 Would send push notification to {recipient.username}: {notification.message}")
        
        # Example FCM implementation (commented out):
        """
        from firebase_admin import messaging
        
        # Get user's FCM tokens
        device_tokens = recipient.fcm_tokens.filter(is_active=True).values_list('token', flat=True)
        
        if not device_tokens:
            return
        
        # Prepare notification data
        title = notification.sender.username if notification.sender else 'WhatsApp Clone'
        body = notification.message if prefs.show_message_preview else 'New message'
        
        # Create FCM message
        message = messaging.MulticastMessage(
            notification=messaging.Notification(
                title=title,
                body=body,
            ),
            data={
                'notification_id': str(notification.id),
                'notification_type': notification.notification_type,
                'conversation_id': notification.conversation_id or '',
                'click_action': 'FLUTTER_NOTIFICATION_CLICK',
            },
            android=messaging.AndroidConfig(
                priority='high',
                notification=messaging.AndroidNotification(
                    icon='notification_icon',
                    color='#25D366',
                    sound='default' if prefs.message_sound_enabled else None,
                    tag=f'conversation_{notification.conversation_id}',  # Groups notifications
                ),
            ),
            apns=messaging.APNSConfig(
                payload=messaging.APNSPayload(
                    aps=messaging.Aps(
                        sound='default' if prefs.message_sound_enabled else None,
                        badge=recipient.notifications.filter(is_read=False).count(),
                    ),
                ),
            ),
            tokens=list(device_tokens),
        )
        
        # Send the message
        response = messaging.send_multicast(message)
        
        print(f'✅ Successfully sent push notification: {response.success_count} succeeded, {response.failure_count} failed')
        """
        
    except Notification.DoesNotExist:
        print(f"❌ Notification {notification_id} not found")
    except Exception as e:
        print(f"❌ Failed to send push notification for {notification_id}: {e}")


@shared_task
def cleanup_old_notifications():
    """
    Periodic task to clean up old read notifications
    Run this daily via Celery Beat
    
    WhatsApp keeps notifications for about 30 days
    """
    from django.utils import timezone
    from datetime import timedelta
    from .utils import clear_old_notifications
    
    # Clear notifications older than 30 days
    deleted_count = clear_old_notifications(days=30)
    
    print(f"🧹 Cleaned up {deleted_count} old notifications")
    
    return deleted_count


@shared_task
def send_digest_email(user_id):
    """
    Send daily/weekly digest email of notifications
    Optional feature for users who prefer digest emails
    
    Args:
        user_id: ID of the user
    """
    try:
        user = User.objects.get(id=user_id)
        
        # Get unread notifications from last 24 hours
        from django.utils import timezone
        from datetime import timedelta
        
        yesterday = timezone.now() - timedelta(days=1)
        
        notifications = Notification.objects.filter(
            recipient=user,
            is_read=False,
            created_at__gte=yesterday
        ).select_related('sender').order_by('-created_at')
        
        if not notifications.exists():
            return
        
        # Count notifications by type
        message_count = notifications.filter(notification_type='message').count()
        group_message_count = notifications.filter(notification_type='group_message').count()
        reaction_count = notifications.filter(notification_type='message_reaction').count()
        
        # Prepare email
        subject = f"You have {notifications.count()} unread notifications"
        
        html_message = f"""
        <html>
            <body style="font-family: Arial, sans-serif;">
                <div style="max-width: 600px; margin: 0 auto; padding: 20px;">
                    <h2 style="color: #25D366;">WhatsApp Clone - Daily Digest</h2>
                    
                    <p>Here's what you missed in the last 24 hours:</p>
                    
                    <ul>
                        {'<li>' + str(message_count) + ' new messages</li>' if message_count > 0 else ''}
                        {'<li>' + str(group_message_count) + ' new group messages</li>' if group_message_count > 0 else ''}
                        {'<li>' + str(reaction_count) + ' reactions to your messages</li>' if reaction_count > 0 else ''}
                    </ul>
                    
                    <p>
                        <a href="{settings.FRONTEND_URL}/chat" 
                           style="background-color: #25D366; color: white; padding: 10px 20px; 
                                  text-decoration: none; border-radius: 5px; display: inline-block;">
                            Open WhatsApp Clone
                        </a>
                    </p>
                </div>
            </body>
        </html>
        """
        
        send_mail(
            subject=subject,
            message=f"You have {notifications.count()} unread notifications",
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        print(f"✅ Digest email sent to {user.email}")
        
    except User.DoesNotExist:
        print(f"❌ User {user_id} not found")
    except Exception as e:
        print(f"❌ Failed to send digest email for user {user_id}: {e}")


@shared_task
def batch_send_notifications(notification_ids):
    """
    Send multiple notifications in batch
    Useful for group messages where many users need to be notified
    
    Args:
        notification_ids: List of notification IDs
    """
    from .utils import send_realtime_notification
    
    notifications = Notification.objects.filter(
        id__in=notification_ids
    ).select_related('recipient', 'sender')
    
    for notification in notifications:
        # Send real-time notification
        send_realtime_notification(notification.recipient, notification)
        
        # Queue push notification if user is offline
        from messaging.services.presence_service import presence_service
        if not presence_service.is_user_online(str(notification.recipient.id)):
            send_push_notification.delay(notification.id)
    
    print(f"✅ Batch sent {len(notification_ids)} notifications")
