from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from django.contrib.auth import get_user_model
from .models import Profile, Follow

User = get_user_model()


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    """Create profile when user is created"""
    if created:
        Profile.objects.create(user=instance)


@receiver(post_save, sender=User)
def save_user_profile(sender, instance, **kwargs):
    """Ensure profile exists when user is saved"""
    # Guard against missing profile
    if not hasattr(instance, 'profile'):
        Profile.objects.get_or_create(user=instance)


@receiver(post_save, sender=Follow)
def update_follow_counts_on_create(sender, instance, created, **kwargs):
    """Update follower/following counts when follow is created"""
    if created:
        # Update follower's following count
        follower_profile, _ = Profile.objects.get_or_create(user=instance.follower)
        follower_profile.update_following_count()
        
        # Update followee's followers count
        followee_profile, _ = Profile.objects.get_or_create(user=instance.followee)
        followee_profile.update_followers_count()


@receiver(post_delete, sender=Follow)
def update_follow_counts_on_delete(sender, instance, **kwargs):
    """Update follower/following counts when follow is deleted"""
    try:
        # Update follower's following count
        follower_profile = Profile.objects.get(user=instance.follower)
        follower_profile.update_following_count()
    except Profile.DoesNotExist:
        pass
    
    try:
        # Update followee's followers count
        followee_profile = Profile.objects.get(user=instance.followee)
        followee_profile.update_followers_count()
    except Profile.DoesNotExist:
        pass
