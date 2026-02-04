from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model
import json
import os

User = get_user_model()


@shared_task
def generate_user_data_export(user_id):
    """Generate user data export (GDPR compliance)"""
    try:
        user = User.objects.get(id=user_id)
        
        # Collect user data
        data = {
            'user': {
                'username': user.username,
                'email': user.email,
                'display_name': user.display_name,
                'created_at': str(user.created_at),
            },
            'profile': {},
            'posts_count': user.posts.count(),
            'followers_count': user.followers.count(),
            'following_count': user.following.count(),
            'reels_count': user.reels.count(),
            'stories_count': user.stories.count(),
            'messages_sent': user.sent_messages.count(),
            'notifications_received': user.notifications.count(),
        }
        
        # Add profile data
        if hasattr(user, 'profile'):
            profile = user.profile
            data['profile'] = {
                'bio': profile.bio,
                'location': profile.location,
                'website': profile.website,
                'is_private': profile.is_private,
            }
        
        # Save to file (in production, save to S3)
        export_dir = os.path.join(settings.MEDIA_ROOT, 'exports')
        os.makedirs(export_dir, exist_ok=True)
        
        filename = f'user_data_{user.id}_{user.username}.json'
        filepath = os.path.join(export_dir, filename)
        
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        
        # Send email with download link
        frontend_url = getattr(settings, 'FRONTEND_URL', 'http://localhost:3000')
        download_url = f"{frontend_url}/download-data/{filename}"
        
        send_mail(
            subject='Your Data Export is Ready',
            message=f"""
Hello {user.username},

Your data export is ready for download:

{download_url}

This link will expire in 7 days.

Best regards,
The Instagram Clone Team
            """,
            from_email=getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@instagram.com'),
            recipient_list=[user.email],
            fail_silently=False,
        )
        
        return f"Data export generated for {user.username}"
    
    except User.DoesNotExist:
        return f"User {user_id} not found"
    except Exception as e:
        return f"Error generating export: {str(e)}"