from django.db import models
from django.contrib.auth import get_user_model
from django.conf import settings
from django.utils import timezone
from django.contrib.contenttypes.models import ContentType
from django.contrib.contenttypes.fields import GenericForeignKey
import os

User = get_user_model()


def post_media_path(instance, filename):
    """Generate upload path for post media"""
    ext = filename.split('.')[-1]
    filename = f"{timezone.now().timestamp()}.{ext}"
    return os.path.join('posts', str(instance.post.user.id), filename)


class Post(models.Model):
    POST_TYPES = (
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
        ('carousel', 'Carousel'),
    )
    
    VISIBILITY_CHOICES = (
        ('public', 'Public'),
        ('followers', 'Followers Only'),
        ('private', 'Private'),
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='posts'
    )
    type = models.CharField(max_length=20, choices=POST_TYPES, default='text')
    caption = models.TextField(max_length=2200, blank=True)
    visibility = models.CharField(max_length=20, choices=VISIBILITY_CHOICES, default='public')
    
    # Denormalized counters for performance
    likes_count = models.PositiveIntegerField(default=0)
    comments_count = models.PositiveIntegerField(default=0)
    views_count = models.PositiveIntegerField(default=0)
    
    # Location (optional)
    location = models.CharField(max_length=200, blank=True)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    # For edited posts
    is_edited = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'posts'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['-created_at']),
            models.Index(fields=['visibility', '-created_at']),
        ]
    
    def __str__(self):
        return f"Post by {self.user.username} at {self.created_at}"
    
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


class PostMedia(models.Model):
    MEDIA_TYPES = (
        ('text', 'Text'),
        ('image', 'Image'),
        ('video', 'Video'),
    )
    
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='media')
    media_type = models.CharField(max_length=10, choices=MEDIA_TYPES)
    file = models.FileField(upload_to=post_media_path, blank=True, null=True)
    thumbnail = models.ImageField(upload_to=post_media_path, blank=True, null=True)
    
    # For text slides
    text_content = models.TextField(max_length=500, blank=True)
    background_color = models.CharField(max_length=7, default='#4A90E2')  # Hex color
    text_color = models.CharField(max_length=7, default='#ffffff')  # Hex color
    
    # Media metadata
    width = models.PositiveIntegerField(null=True, blank=True)
    height = models.PositiveIntegerField(null=True, blank=True)
    duration = models.FloatField(null=True, blank=True)  # For videos in seconds
    
    order = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'post_media'
        ordering = ['order']
        indexes = [
            models.Index(fields=['post', 'order']),
        ]
    
    def __str__(self):
        return f"{self.media_type} for post {self.post.id}"


class Like(models.Model):
    TARGET_TYPES = (
        ('post', 'Post'),
        ('comment', 'Comment'),
        ('reply', 'Reply'),
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='likes'
    )
    target_type = models.CharField(max_length=10, choices=TARGET_TYPES)
    target_id = models.PositiveIntegerField()
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'likes'
        unique_together = ('user', 'target_type', 'target_id')
        indexes = [
            models.Index(fields=['target_type', 'target_id', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} likes {self.target_type} {self.target_id}"


class Comment(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='comments')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='comments'
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
    reactions_count = models.PositiveIntegerField(default=0)
    
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    is_edited = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'comments'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['post', '-created_at']),
            models.Index(fields=['parent', '-created_at']),
            models.Index(fields=['user', '-created_at']),
        ]
    
    def __str__(self):
        return f"Comment by {self.user.username} on post {self.post.id}"
    
    def increment_likes(self):
        self.likes_count = models.F('likes_count') + 1
        self.save(update_fields=['likes_count'])
        self.refresh_from_db(fields=['likes_count'])
    
    def decrement_likes(self):
        self.likes_count = models.F('likes_count') - 1
        self.save(update_fields=['likes_count'])
        self.refresh_from_db(fields=['likes_count'])
    
    def increment_reactions(self):
        self.reactions_count = models.F('reactions_count') + 1
        self.save(update_fields=['reactions_count'])
        self.refresh_from_db(fields=['reactions_count'])
    
    def decrement_reactions(self):
        self.reactions_count = models.F('reactions_count') - 1
        self.save(update_fields=['reactions_count'])
        self.refresh_from_db(fields=['reactions_count'])
    
    def get_reactions_breakdown(self):
        """Get count of each reaction type"""
        from django.db.models import Count
        reactions = Reaction.objects.filter(
            target_type='comment',
            target_id=self.id
        ).values('reaction_type').annotate(count=Count('id'))
        
        return {item['reaction_type']: item['count'] for item in reactions}
    

    def get_reactions_breakdown(self):
        """Get count of each reaction type with emojis"""
        from django.db.models import Count
        
        reactions = Reaction.objects.filter(
            target_type='comment',
            target_id=self.id
        ).values('reaction_type').annotate(count=Count('id'))
        
        # Convert reaction_type to emoji
        breakdown = {}
        reaction_types_dict = dict(Reaction.REACTION_TYPES)
        
        for item in reactions:
            reaction_type = item['reaction_type']
            emoji = reaction_types_dict.get(reaction_type, '')
            if emoji:
                breakdown[emoji] = item['count']
        
        print(f"Reactions breakdown for comment {self.id}: {breakdown}")  # Debug log
        return breakdown

class Reaction(models.Model):
    """
    Model to track emoji reactions on posts and comments
    """
    REACTION_TYPES = (
        ('grinning', '😀'),
        ('joy', '😂'),
        ('heart_eyes', '😍'),
        ('smiling_hearts', '🥰'),
        ('blush', '😊'),
        ('cool', '😎'),
        ('star_eyes', '🤩'),
        ('sob', '😭'),
        ('cry', '😢'),
        ('rage', '😡'),
        ('thumbs_up', '👍'),
        ('clap', '👏'),
        ('pray', '🙏'),
        ('heart', '❤️'),
        ('fire', '🔥'),
        ('sparkles', '✨'),
        ('hundred', '💯'),
        ('party', '🎉'),
        ('scream', '😱'),
        ('thinking', '🤔'),
    )
    
    TARGET_TYPES = (
        ('post', 'Post'),
        ('comment', 'Comment'),
    )
    
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='reactions'
    )
    target_type = models.CharField(max_length=10, choices=TARGET_TYPES)
    target_id = models.PositiveIntegerField()
    reaction_type = models.CharField(max_length=50, choices=REACTION_TYPES)
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'reactions'
        unique_together = ('user', 'target_type', 'target_id')
        indexes = [
            models.Index(fields=['target_type', 'target_id', '-created_at']),
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['target_type', 'target_id', 'reaction_type']),
        ]
    
    def __str__(self):
        emoji = dict(self.REACTION_TYPES).get(self.reaction_type, '')
        return f"{self.user.username} reacted {emoji} to {self.target_type} {self.target_id}"
    
    @property
    def get_emoji(self):
        """Property to get the emoji for the reaction"""
        return dict(self.REACTION_TYPES).get(self.reaction_type, '')



class SavedPost(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='saved_posts'
    )
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='saved_by')
    folder = models.CharField(max_length=100, blank=True)  # For collections
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'saved_posts'
        unique_together = ('user', 'post')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', '-created_at']),
            models.Index(fields=['user', 'folder', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.user.username} saved post {self.post.id}"


class Tag(models.Model):
    name = models.CharField(max_length=100, unique=True, db_index=True)
    usage_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'tags'
        ordering = ['-usage_count']
    
    def __str__(self):
        return f"#{self.name}"

class Mention(models.Model):
    """
    Model to track user mentions in posts and comments
    Uses GenericForeignKey to work with both Post and Comment models
    """
    mentioned_user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='mentions_received'
    )
    
    mentioned_by = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='mentions_created'
    )
    
    content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    object_id = models.PositiveIntegerField()
    content_object = GenericForeignKey('content_type', 'object_id')
    
    position = models.IntegerField(default=0, help_text="Character position in text")
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'mentions'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['mentioned_user', '-created_at']),
            models.Index(fields=['content_type', 'object_id']),
        ]
        unique_together = ['mentioned_user', 'content_type', 'object_id']
    
    def __str__(self):
        return f"{self.mentioned_by.username} mentioned {self.mentioned_user.username}"

class PostTag(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name='post_tags')
    tag = models.ForeignKey(Tag, on_delete=models.CASCADE, related_name='tagged_posts')
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'post_tags'
        unique_together = ('post', 'tag')
        indexes = [
            models.Index(fields=['tag', '-created_at']),
        ]
    
    def __str__(self):
        return f"Post {self.post.id} tagged with {self.tag.name}"