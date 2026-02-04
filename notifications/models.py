from django.db import models
from django.conf import settings
from django.utils import timezone
import json


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        # Message notifications (WhatsApp style)
        ('message', 'New Message'),  # Direct message
        ('group_message', 'Group Message'),  # Group message
        ('message_reaction', 'Message Reaction'),  # Someone reacted to your message
        ('message_reply', 'Message Reply'),  # Someone replied to your message
        ('mention', 'Mention'),  # Someone mentioned you (@username)
        
        # Call notifications
        ('call_missed', 'Missed Call'),  # Missed voice/video call
        ('call_rejected', 'Call Rejected'),  # Call was rejected
        
        # Group notifications
        ('group_added', 'Added to Group'),  # Someone added you to a group
        ('group_removed', 'Removed from Group'),  # Someone removed you from group
        ('group_admin', 'Made Group Admin'),  # You were made admin
        ('group_subject_changed', 'Group Name Changed'),  # Group name changed
        
        # Status updates (for future)
        ('status_view', 'Status View'),  # Someone viewed your status
        ('status_reply', 'Status Reply'),  # Someone replied to your status
    )
    
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications'
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='sent_notifications',
        null=True,
        blank=True  # Can be null for system notifications
    )
    
    notification_type = models.CharField(max_length=30, choices=NOTIFICATION_TYPES, db_index=True)
    
    # Generic relation fields
    target_type = models.CharField(max_length=20, blank=True)  # message, call, conversation, etc.
    target_id = models.UUIDField(null=True, blank=True)  # UUID of the target object
    
    # JSON payload for additional data
    payload = models.JSONField(default=dict, blank=True)
    
    # Message to display
    message = models.TextField(blank=True)
    
    # Status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['sender', '-created_at']),
            models.Index(fields=['notification_type', '-created_at']),
            models.Index(fields=['recipient', 'notification_type', 'is_read']),
        ]
    
    def __str__(self):
        return f"{self.notification_type} for {self.recipient.username}"
    
    def mark_as_read(self):
        """Mark notification as read"""
        if not self.is_read:
            self.is_read = True
            self.read_at = timezone.now()
            self.save(update_fields=['is_read', 'read_at'])
    
    def get_payload_data(self, key, default=None):
        """Safely get data from JSON payload"""
        return self.payload.get(key, default)
    
    def set_payload_data(self, key, value):
        """Safely set data in JSON payload"""
        if not isinstance(self.payload, dict):
            self.payload = {}
        self.payload[key] = value
        self.save(update_fields=['payload'])
    
    @property
    def conversation_id(self):
        """Get conversation ID from payload"""
        return self.payload.get('conversation_id')
    
    @property
    def is_group_notification(self):
        """Check if this is a group-related notification"""
        return self.notification_type in [
            'group_message', 'group_added', 'group_removed',
            'group_admin', 'group_subject_changed'
        ]


class NotificationPreference(models.Model):
    """
    User preferences for notifications (WhatsApp style)
    """
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    
    # ============ MESSAGE NOTIFICATIONS ============
    # In-app notifications
    notify_on_message = models.BooleanField(default=True)
    notify_on_group_message = models.BooleanField(default=True)
    notify_on_reaction = models.BooleanField(default=True)
    notify_on_reply = models.BooleanField(default=True)
    notify_on_mention = models.BooleanField(default=True)
    
    # Call notifications
    notify_on_call = models.BooleanField(default=True)
    
    # ============ PUSH NOTIFICATIONS ============
    push_on_message = models.BooleanField(default=True)
    push_on_group_message = models.BooleanField(default=True)
    push_on_reaction = models.BooleanField(default=True)
    push_on_reply = models.BooleanField(default=True)
    push_on_mention = models.BooleanField(default=True)
    push_on_call = models.BooleanField(default=True)
    
    # ============ EMAIL NOTIFICATIONS ============
    # (Most users disable these on WhatsApp)
    email_on_message = models.BooleanField(default=False)
    email_on_group_message = models.BooleanField(default=False)
    
    # ============ NOTIFICATION SOUNDS ============
    message_sound_enabled = models.BooleanField(default=True)
    group_message_sound_enabled = models.BooleanField(default=True)
    call_sound_enabled = models.BooleanField(default=True)
    
    # Sound/ringtone choices (can be expanded)
    message_tone = models.CharField(max_length=50, default='default', blank=True)
    notification_tone = models.CharField(max_length=50, default='default', blank=True)
    ringtone = models.CharField(max_length=50, default='default', blank=True)
    
    # ============ VIBRATION ============
    vibrate_on_message = models.BooleanField(default=True)
    vibrate_on_call = models.BooleanField(default=True)
    
    # ============ MESSAGE PREVIEW ============
    show_message_preview = models.BooleanField(default=True)  # Show message content in notification
    show_sender_name = models.BooleanField(default=True)  # Show sender name
    
    # ============ GENERAL SETTINGS ============
    pause_all = models.BooleanField(default=False)  # Mute all notifications
    pause_until = models.DateTimeField(null=True, blank=True)  # Mute until specific time
    
    # Notification light (for devices with LED)
    notification_light_enabled = models.BooleanField(default=True)
    notification_light_color = models.CharField(max_length=7, default='#25D366', blank=True)  # WhatsApp green
    
    # High priority notifications
    high_priority_notifications = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'notification_preferences'
    
    def __str__(self):
        return f"Notification preferences for {self.user.username}"
    
    def should_notify(self, notification_type):
        """
        Check if user wants this type of notification
        
        Args:
            notification_type: Type of notification
        
        Returns:
            bool: True if user should be notified
        """
        # Check if all notifications are paused
        if self.pause_all:
            return False
        
        # Check if paused until a specific time
        if self.pause_until and timezone.now() < self.pause_until:
            return False
        
        # Map notification types to preference fields
        type_map = {
            'message': self.notify_on_message,
            'group_message': self.notify_on_group_message,
            'message_reaction': self.notify_on_reaction,
            'message_reply': self.notify_on_reply,
            'mention': self.notify_on_mention,
            'call_missed': self.notify_on_call,
            'call_rejected': self.notify_on_call,
        }
        
        return type_map.get(notification_type, True)
    
    def should_send_push(self, notification_type):
        """Check if push notification should be sent"""
        if self.pause_all:
            return False
        
        type_map = {
            'message': self.push_on_message,
            'group_message': self.push_on_group_message,
            'message_reaction': self.push_on_reaction,
            'message_reply': self.push_on_reply,
            'mention': self.push_on_mention,
            'call_missed': self.push_on_call,
        }
        
        return type_map.get(notification_type, True)
    
    def is_currently_muted(self):
        """Check if notifications are currently muted"""
        if self.pause_all:
            return True
        
        if self.pause_until and timezone.now() < self.pause_until:
            return True
        
        return False


class NotificationGroup(models.Model):
    """
    Group similar notifications together
    WhatsApp groups like: "John and 3 others sent you messages"
    """
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_groups'
    )
    
    notification_type = models.CharField(max_length=30)
    target_type = models.CharField(max_length=20)
    target_id = models.UUIDField()  # Conversation ID usually
    
    # Store list of senders
    senders = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='grouped_notifications'
    )
    
    count = models.PositiveIntegerField(default=0)
    is_read = models.BooleanField(default=False)
    
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'notification_groups'
        unique_together = ('recipient', 'notification_type', 'target_type', 'target_id')
        ordering = ['-last_updated']
        indexes = [
            models.Index(fields=['recipient', '-last_updated']),
            models.Index(fields=['recipient', 'is_read']),
        ]
    
    def __str__(self):
        return f"Group: {self.notification_type} for {self.recipient.username}"
    
    def get_preview_message(self):
        """Generate preview message for grouped notification"""
        senders = self.senders.all()[:3]
        count = self.senders.count()
        
        if count == 0:
            return ""
        elif count == 1:
            sender = senders[0]
            return f"{sender.username} sent you a message"
        elif count == 2:
            return f"{senders[0].username} and {senders[1].username} sent you messages"
        else:
            return f"{senders[0].username} and {count - 1} others sent you messages"


# Signal to create default preferences when user is created
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.contrib.auth import get_user_model

User = get_user_model()

@receiver(post_save, sender=User)
def create_notification_preferences(sender, instance, created, **kwargs):
    """Create default notification preferences for new users"""
    if created:
        NotificationPreference.objects.create(user=instance)