from django.db import models
from django.conf import settings
from django.utils import timezone
import json


class Notification(models.Model):
    NOTIFICATION_TYPES = (
        ('like_post', 'Post Like'),
        ('like_comment', 'Comment Like'),
        ('comment', 'Comment on Post'),
        ('reply', 'Comment Reply'),
        ('follow', 'New Follower'),
        ('mention', 'Mention'),
        ('story_view', 'Story View'),
        ('post_tag', 'Tagged in Post'),
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
        blank=True
    )
    
    notification_type = models.CharField(max_length=20, choices=NOTIFICATION_TYPES)
    
    # Generic relation fields
    target_type = models.CharField(max_length=20, blank=True)  # post, comment, story, etc.
    target_id = models.PositiveIntegerField(null=True, blank=True)
    
    # JSON payload for additional data
    payload = models.JSONField(default=dict, blank=True)
    
    # Message to display
    message = models.TextField(blank=True)
    
    # Status
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        db_table = 'notifications'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', '-created_at']),
            models.Index(fields=['recipient', 'is_read', '-created_at']),
            models.Index(fields=['sender', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.notification_type} for {self.recipient.username}"
    
    def mark_as_read(self):
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


class NotificationPreference(models.Model):
    """User preferences for notifications"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_preferences'
    )
    
    # Email notifications
    email_on_like = models.BooleanField(default=False)
    email_on_comment = models.BooleanField(default=True)
    email_on_follow = models.BooleanField(default=True)
    email_on_mention = models.BooleanField(default=True)
    
    # Push notifications (for future mobile app)
    push_on_like = models.BooleanField(default=True)
    push_on_comment = models.BooleanField(default=True)
    push_on_follow = models.BooleanField(default=True)
    push_on_mention = models.BooleanField(default=True)
    push_on_story_view = models.BooleanField(default=False)
    
    # In-app notifications
    notify_on_like = models.BooleanField(default=True)
    notify_on_comment = models.BooleanField(default=True)
    notify_on_follow = models.BooleanField(default=True)
    notify_on_mention = models.BooleanField(default=True)
    notify_on_story_view = models.BooleanField(default=True)
    
    # General settings
    pause_all = models.BooleanField(default=False)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'notification_preferences'
    
    def __str__(self):
        return f"Notification preferences for {self.user.username}"
    
    def should_notify(self, notification_type):
        """Check if user wants this type of notification"""
        if self.pause_all:
            return False
        
        type_map = {
            'like_post': self.notify_on_like,
            'like_comment': self.notify_on_like,
            'comment': self.notify_on_comment,
            'reply': self.notify_on_comment,
            'follow': self.notify_on_follow,
            'mention': self.notify_on_mention,
            'story_view': self.notify_on_story_view,
        }
        
        return type_map.get(notification_type, True)


class NotificationGroup(models.Model):
    """Group similar notifications together (e.g., "John and 5 others liked your post")"""
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notification_groups'
    )
    
    notification_type = models.CharField(max_length=20)
    target_type = models.CharField(max_length=20)
    target_id = models.PositiveIntegerField()
    
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
        ]
    
    def __str__(self):
        return f"Group: {self.notification_type} for {self.recipient.username}"