from django.db import models
from django.conf import settings
from django.utils import timezone


class PrivacySettings(models.Model):
    """Privacy and security settings"""
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='privacy_settings'
    )
    
    # Account Privacy
    is_private = models.BooleanField(default=False, help_text="Private account")
    
    # Activity Status
    show_activity_status = models.BooleanField(default=True, help_text="Show when you're active")
    
    # Story Settings
    allow_story_sharing = models.BooleanField(default=True, help_text="Allow others to share your story")
    allow_story_replies = models.BooleanField(default=True, help_text="Allow replies to your story")
    hide_story_from = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='hidden_stories_from',
        blank=True,
        help_text="Users who can't see your stories"
    )
    
    # Post Settings
    allow_comments = models.BooleanField(default=True, help_text="Allow comments on your posts")
    allow_comment_likes = models.BooleanField(default=True, help_text="Allow likes on comments")
    hide_like_counts = models.BooleanField(default=False, help_text="Hide like counts on your posts")
    
    # Tagging
    allow_tags = models.BooleanField(default=True, help_text="Allow others to tag you")
    manual_tag_approval = models.BooleanField(default=False, help_text="Manually approve tags")
    
    # Mentions
    allow_mentions = models.BooleanField(default=True, help_text="Allow others to mention you")
    mentions_from = models.CharField(
        max_length=20,
        choices=[
            ('everyone', 'Everyone'),
            ('following', 'People you follow'),
            ('no_one', 'No one')
        ],
        default='everyone'
    )
    
    # Messages
    allow_messages_from = models.CharField(
        max_length=20,
        choices=[
            ('everyone', 'Everyone'),
            ('following', 'People you follow'),
            ('no_one', 'No one')
        ],
        default='everyone'
    )
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'privacy_settings'
        verbose_name_plural = 'Privacy Settings'
    
    def __str__(self):
        return f"Privacy settings for {self.user.username}"


class BlockedUser(models.Model):
    """Blocked users list"""
    blocker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='blocking'
    )
    blocked = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='blocked_by'
    )
    blocked_at = models.DateTimeField(default=timezone.now)
    reason = models.CharField(max_length=200, blank=True)
    
    class Meta:
        db_table = 'blocked_users'
        unique_together = ('blocker', 'blocked')
        ordering = ['-blocked_at']
        indexes = [
            models.Index(fields=['blocker', '-blocked_at']),
            models.Index(fields=['blocked']),
        ]
    
    def __str__(self):
        return f"{self.blocker.username} blocked {self.blocked.username}"


class MutedUser(models.Model):
    """Muted users list (hide their content)"""
    muter = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='muting'
    )
    muted = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='muted_by'
    )
    
    # What to mute
    mute_posts = models.BooleanField(default=True)
    mute_stories = models.BooleanField(default=True)
    mute_reels = models.BooleanField(default=True)
    
    muted_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'muted_users'
        unique_together = ('muter', 'muted')
        ordering = ['-muted_at']
    
    def __str__(self):
        return f"{self.muter.username} muted {self.muted.username}"


class RestrictedUser(models.Model):
    """Restricted users (limited interaction)"""
    restrictor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='restricting'
    )
    restricted = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='restricted_by'
    )
    restricted_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'restricted_users'
        unique_together = ('restrictor', 'restricted')
        ordering = ['-restricted_at']
    
    def __str__(self):
        return f"{self.restrictor.username} restricted {self.restricted.username}"


class ActivityLog(models.Model):
    """User activity log for security"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='activity_logs'
    )
    
    ACTION_TYPES = (
        ('login', 'Login'),
        ('logout', 'Logout'),
        ('password_change', 'Password Change'),
        ('password_reset', 'Password Reset'),
        ('email_change', 'Email Change'),
        ('profile_update', 'Profile Update'),
        ('settings_change', 'Settings Change'),
    )
    
    action_type = models.CharField(max_length=20, choices=ACTION_TYPES)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)
    device = models.CharField(max_length=100, blank=True)
    location = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    
    class Meta:
        db_table = 'activity_logs'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} - {self.action_type} at {self.created_at}"


class CloseFriendsList(models.Model):
    """Close friends list for stories"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='close_friends_list'
    )
    close_friend = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='close_friend_of'
    )
    added_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'close_friends'
        unique_together = ('user', 'close_friend')
        ordering = ['-added_at']
    
    def __str__(self):
        return f"{self.close_friend.username} is close friend of {self.user.username}"