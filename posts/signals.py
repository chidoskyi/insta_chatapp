from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from posts.tasks import generate_thumbnail, process_video_metadata
from .models import PostMedia, Post
import os


@receiver(post_save, sender=PostMedia)
def process_media_after_save(sender, instance, created, **kwargs):
    """Trigger background tasks after media is saved"""
    if created and instance.file:
        if instance.media_type == 'image':
            # Generate thumbnail asynchronously
            from .tasks import generate_thumbnail
            generate_thumbnail.delay(instance.id)
        elif instance.media_type == 'video':
            # Process video metadata asynchronously
            from .tasks import process_video_metadata
            process_video_metadata.delay(instance.id)


@receiver(post_delete, sender=PostMedia)
def delete_media_files(sender, instance, **kwargs):
    """Delete media files when PostMedia is deleted"""
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)
    
    if instance.thumbnail:
        if os.path.isfile(instance.thumbnail.path):
            os.remove(instance.thumbnail.path)


@receiver(post_delete, sender=Post)
def delete_post_media_files(sender, instance, **kwargs):
    """Delete all media when post is deleted"""
    for media in instance.media.all():
        if media.file:
            if os.path.isfile(media.file.path):
                os.remove(media.file.path)
        if media.thumbnail:
            if os.path.isfile(media.thumbnail.path):
                os.remove(media.thumbnail.path)


@receiver(post_save, sender=Post)
def update_posts_count_on_create(sender, instance, created, **kwargs):
    """Update user's posts count when post is created"""
    if created:
        from accounts.models import Profile
        profile, _ = Profile.objects.get_or_create(user=instance.user)
        profile.update_posts_count()


@receiver(post_delete, sender=Post)
def update_posts_count_on_delete(sender, instance, **kwargs):
    """Update user's posts count when post is deleted"""
    from accounts.models import Profile
    try:
        profile = Profile.objects.get(user=instance.user)
        profile.update_posts_count()
    except Profile.DoesNotExist:
        pass
def process_media_after_save(sender, instance, created, **kwargs):
    """Trigger background tasks after media is saved"""
    if created and instance.file:
        if instance.media_type == 'image':
            # Generate thumbnail asynchronously
            generate_thumbnail.delay(instance.id)
        elif instance.media_type == 'video':
            # Process video metadata asynchronously
            process_video_metadata.delay(instance.id)


@receiver(post_delete, sender=PostMedia)
def delete_media_files(sender, instance, **kwargs):
    """Delete media files when PostMedia is deleted"""
    if instance.file:
        if os.path.isfile(instance.file.path):
            os.remove(instance.file.path)
    
    if instance.thumbnail:
        if os.path.isfile(instance.thumbnail.path):
            os.remove(instance.thumbnail.path)


@receiver(post_delete, sender=Post)
def delete_post_media_files(sender, instance, **kwargs):
    """Delete all media when post is deleted"""
    for media in instance.media.all():
        if media.file:
            if os.path.isfile(media.file.path):
                os.remove(media.file.path)
        if media.thumbnail:
            if os.path.isfile(media.thumbnail.path):
                os.remove(media.thumbnail.path)