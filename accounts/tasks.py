from celery import shared_task
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth import get_user_model
from django.template.loader import render_to_string
from django.utils.html import strip_tags

User = get_user_model()


@shared_task(bind=True, max_retries=3)
def send_password_reset_email(self, user_id, uid, token):
    """
    Send password reset email to user
    """
    try:
        user = User.objects.get(pk=user_id)
        
        # Build reset URL
        reset_url = f"{settings.FRONTEND_URL}/reset-password?uid={uid}&token={token}"
        
        # Context for email template
        context = {
            'user': user,
            'reset_url': reset_url,
            'site_name': getattr(settings, 'SITE_NAME', 'InstaChatApp'),
        }
        
        # Render HTML email
        html_message = render_to_string('emails/password_reset.html', context)
        plain_message = strip_tags(html_message)
        
        # Send email
        send_mail(
            subject='Reset Your Password',
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return f"Password reset email sent to {user.email}"
        
    except User.DoesNotExist:
        return f"User with ID {user_id} not found"
    except Exception as exc:
        # Retry on failure
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def send_welcome_email(self, user_id):
    """
    Send welcome email to new user
    """
    try:
        user = User.objects.get(pk=user_id)
        
        context = {
            'user': user,
            'site_name': getattr(settings, 'SITE_NAME', 'InstaChatApp'),
            'login_url': f"{settings.FRONTEND_URL}/login",
        }
        
        html_message = render_to_string('emails/welcome.html', context)
        plain_message = strip_tags(html_message)
        
        send_mail(
            subject='Welcome to InstaChatApp!',
            message=plain_message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[user.email],
            html_message=html_message,
            fail_silently=False,
        )
        
        return f"Welcome email sent to {user.email}"
        
    except User.DoesNotExist:
        return f"User with ID {user_id} not found"
    except Exception as exc:
        raise self.retry(exc=exc, countdown=60)