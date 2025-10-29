from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from posts.models import Like, Comment
from accounts.models import Follow
from stories.models import StoryView
from .utils import (
    notify_post_like,
    notify_comment_like,
    notify_comment,
    notify_reply,
    notify_follow,
    notify_story_view,
    delete_notification
)


@receiver(post_save, sender=Like)
def handle_like_notification(sender, instance, created, **kwargs):
    """Create notification when someone likes a post or comment"""
    if created:
        if instance.target_type == 'post':
            # Get the post
            from posts.models import Post
            try:
                post = Post.objects.get(id=instance.target_id)
                notify_post_like(post, instance.user)
            except Post.DoesNotExist:
                pass
        
        elif instance.target_type == 'comment':
            # Get the comment
            try:
                comment = Comment.objects.get(id=instance.target_id)
                notify_comment_like(comment, instance.user)
            except Comment.DoesNotExist:
                pass


@receiver(post_delete, sender=Like)
def handle_unlike_notification(sender, instance, **kwargs):
    """Delete notification when someone unlikes"""
    if instance.target_type == 'post':
        delete_notification(
            recipient=None,  # Will be inferred from target
            notification_type='like_post',
            target_type='post',
            target_id=instance.target_id,
            sender=instance.user
        )
        # Try to get the post owner and delete notification
        from posts.models import Post
        try:
            post = Post.objects.get(id=instance.target_id)
            delete_notification(
                recipient=post.user,
                notification_type='like_post',
                target_type='post',
                target_id=instance.target_id,
                sender=instance.user
            )
        except Post.DoesNotExist:
            pass
    
    elif instance.target_type == 'comment':
        try:
            comment = Comment.objects.get(id=instance.target_id)
            delete_notification(
                recipient=comment.user,
                notification_type='like_comment',
                target_type='comment',
                target_id=instance.target_id,
                sender=instance.user
            )
        except Comment.DoesNotExist:
            pass


@receiver(post_save, sender=Comment)
def handle_comment_notification(sender, instance, created, **kwargs):
    """Create notification for new comment or reply"""
    if created:
        if instance.parent:
            # It's a reply
            notify_reply(instance.parent, instance.user, instance)
        else:
            # It's a comment on a post
            notify_comment(instance.post, instance.user, instance)


@receiver(post_save, sender=Follow)
def handle_follow_notification(sender, instance, created, **kwargs):
    """Create notification when someone follows you"""
    if created:
        notify_follow(instance.followee, instance.follower)


@receiver(post_delete, sender=Follow)
def handle_unfollow_notification(sender, instance, **kwargs):
    """Delete notification when someone unfollows"""
    delete_notification(
        recipient=instance.followee,
        notification_type='follow',
        target_type='',
        target_id=None,
        sender=instance.follower
    )


@receiver(post_save, sender=StoryView)
def handle_story_view_notification(sender, instance, created, **kwargs):
    """Create notification when someone views your story"""
    if created:
        notify_story_view(instance.story, instance.viewer)