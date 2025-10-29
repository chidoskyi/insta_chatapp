from django.db import models
from django.conf import settings
from django.utils import timezone
import os


def reel_video_path(instance, filename):
    """Generate upload path for reel videos"""
    ext = filename.split('.')[-1]
    filename = f"{timezone.now().timestamp()}.{ext}"
    return os.path.join('reels', str(instance.user.id), filename)


class Reel(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reels'
    )
    
    # Video file (required)
    video = models.FileField(upload_to=reel_video_path)
    thumbnail = models.ImageField(upload_to=reel_video_path, blank=True, null=True)
    
    # Video metadata
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)  # in seconds
    
    # Content
    caption = models.TextField(max_length=2200, blank=True)
    
    # Audio/Music (optional)
    audio_name = models.CharField(max_length=200, blank=True)
    audio_url = models.URLField(blank=True)
    
    # Denormalized counters
    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    shares_count = models.PositiveIntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # Status
    is_edited = models.BooleanField(default=False)
    is_deleted = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'reels'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['-views_count']),
        ]
    
    def __str__(self):
        return f"Reel by {self.user.username} at {self.created_at}"
    
    def increment_likes(self):
        self.likes_count = models.F('likes_count') + 1
        self.save(update_fields=['likes_count'])
        self.refresh_from_db(fields=['likes_count'])
    
    def decrement_likes(self):
        self.likes_count = models.F('likes_count') - 1
        self.save(update_fields=['likes_count'])
        self.refresh_from_db(fields=['likes_count'])
    
    def increment_comments(self):
        self.comments_count = models.F('comments_count') + 1
        self.save(update_fields=['comments_count'])
        self.refresh_from_db(fields=['comments_count'])
    
    def decrement_comments(self):
        self.comments_count = models.F('comments_count') - 1
        self.save(update_fields=['comments_count'])
        self.refresh_from_db(fields=['comments_count'])
    
    def increment_views(self):
        self.views_count = models.F('views_count') + 1
        self.save(update_fields=['views_count'])
        self.refresh_from_db(fields=['views_count'])
    
    def increment_shares(self):
        self.shares_count = models.F('shares_count') + 1
        self.save(update_fields=['shares_count'])
        self.refresh_from_db(fields=['shares_count'])


class ReelLike(models.Model):
    """Likes on reels (separate from posts to allow different analytics)"""
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='likes')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reel_likes'
    )
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'reel_likes'
        unique_together = ('reel', 'user')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reel', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} likes reel {self.reel.id}"


class ReelComment(models.Model):
    """Comments on reels"""
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reel_comments'
    )
    parent = models.ForeignKey(
        'self',
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='replies'
    )
    body = models.TextField(max_length=500)
    
    # Denormalized counter
    likes_count = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'reel_comments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['reel', '-created_at']),
            models.Index(fields=['parent', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"Comment by {self.user.username} on reel {self.reel.id}"
    
    def increment_likes(self):
        self.likes_count = models.F('likes_count') + 1
        self.save(update_fields=['likes_count'])
        self.refresh_from_db(fields=['likes_count'])
    
    def decrement_likes(self):
        self.likes_count = models.F('likes_count') - 1
        self.save(update_fields=['likes_count'])
        self.refresh_from_db(fields=['likes_count'])


class ReelCommentLike(models.Model):
    """Likes on reel comments"""
    comment = models.ForeignKey(
        ReelComment,
        on_delete=models.CASCADE,
        related_name='likes'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reel_comment_likes'
    )
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'reel_comment_likes'
        unique_together = ('comment', 'user')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.user.username} likes comment {self.comment.id}"


class ReelView(models.Model):
    """Track reel views"""
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='views')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reel_views',
        null=True,
        blank=True  # Allow anonymous views
    )
    session_key = models.CharField(max_length=40, null=True, blank=True)  # For anonymous users
    viewed_at = models.DateTimeField(default=timezone.now)
    watch_time = models.FloatField(default=0)  # How long user watched (seconds)
    completed = models.BooleanField(default=False)  # Did they watch till end?
    
    class Meta:
        db_table = 'reel_views'
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['reel', '-viewed_at']),
            models.Index(fields=['user', '-viewed_at']),
        ]
    
    def __str__(self):
        viewer = self.user.username if self.user else 'Anonymous'
        return f"{viewer} viewed reel {self.reel.id}"


class SavedReel(models.Model):
    """Saved reels by users"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_reels'
    )
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='saved_by')
    folder = models.CharField(max_length=100, blank=True)  # For collections
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'saved_reels'
        unique_together = ('user', 'reel')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} saved reel {self.reel.id}"


class ReelTag(models.Model):
    """Tags for reels"""
    reel = models.ForeignKey(Reel, on_delete=models.CASCADE, related_name='tags')
    tag = models.ForeignKey('posts.Tag', on_delete=models.CASCADE, related_name='tagged_reels')
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'reel_tags'
        unique_together = ('reel', 'tag')
    
    def __str__(self):
        return f"Reel {self.reel.id} tagged with {self.tag.name}"