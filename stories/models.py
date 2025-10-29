from django.db import models
from django.conf import settings
from django.utils import timezone
from datetime import timedelta
import os


def story_media_path(instance, filename):
    """Generate upload path for story media"""
    ext = filename.split('.')[-1]
    filename = f"{timezone.now().timestamp()}.{ext}"
    return os.path.join('stories', str(instance.user.id), filename)


class Story(models.Model):
    MEDIA_TYPES = (
        ('image', 'Image'),
        ('video', 'Video'),
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='stories'
    )
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES)
    media = models.FileField(upload_to=story_media_path)
    thumbnail = models.ImageField(upload_to=story_media_path, blank=True, null=True)
    
    # Media metadata
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)  # For videos in seconds
    
    # Content
    caption = models.TextField(max_length=500, blank=True)
    
    # Denormalized counter
    viewers_count = models.PositiveIntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(db_index=True)
    
    class Meta:
        db_table = 'stories'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['expires_at']),
            models.Index(fields=['-created_at']),
        ]
        verbose_name_plural = 'Stories'
    
    def save(self, *args, **kwargs):
        # Set expiration time to 24 hours from now if not set
        if not self.expires_at:
            self.expires_at = timezone.now() + timedelta(hours=24)
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"Story by {self.user.username} at {self.created_at}"
    
    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at
    
    @property
    def time_remaining(self):
        """Return time remaining in seconds"""
        if self.is_expired:
            return 0
        delta = self.expires_at - timezone.now()
        return int(delta.total_seconds())
    
    def increment_viewers(self):
        self.viewers_count = models.F('viewers_count') + 1
        self.save(update_fields=['viewers_count'])
        self.refresh_from_db(fields=['viewers_count'])


class StoryView(models.Model):
    story = models.ForeignKey(Story, on_delete=models.CASCADE, related_name='views')
    viewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='story_views'
    )
    viewed_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'story_views'
        unique_together = ('story', 'viewer')
        ordering = ['-viewed_at']
        indexes = [
            models.Index(fields=['story', '-viewed_at']),
            models.Index(fields=['viewer', '-viewed_at']),
        ]
    
    def __str__(self):
        return f"{self.viewer.username} viewed story {self.story.id}"


class StoryHighlight(models.Model):
    """Saved stories collections (beyond 24 hours)"""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='highlights'
    )
    title = models.CharField(max_length=100)
    cover_image = models.ImageField(upload_to='highlights/', blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'story_highlights'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username}'s highlight: {self.title}"


class HighlightStory(models.Model):
    """Stories added to highlights"""
    highlight = models.ForeignKey(
        StoryHighlight,
        on_delete=models.CASCADE,
        related_name='stories'
    )
    story = models.ForeignKey(
        Story,
        on_delete=models.CASCADE,
        related_name='in_highlights'
    )
    order = models.PositiveSmallIntegerField(default=0)
    added_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'highlight_stories'
        unique_together = ('highlight', 'story')
        ordering = ['order', '-added_at']
    
    def __str__(self):
        return f"Story {self.story.id} in highlight {self.highlight.title}"


class HighlightPost(models.Model):
    """Posts added to highlights (not just stories)"""
    highlight = models.ForeignKey(
        StoryHighlight,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    post = models.ForeignKey(
        'posts.Post',
        on_delete=models.CASCADE,
        related_name='in_highlights'
    )
    order = models.PositiveSmallIntegerField(default=0)
    added_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'highlight_posts'
        unique_together = ('highlight', 'post')
        ordering = ['order', '-added_at']
    
    def __str__(self):
        return f"Post {self.post.id} in highlight {self.highlight.title}"