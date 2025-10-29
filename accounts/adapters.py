from allauth.account.adapter import DefaultAccountAdapter
from allauth.socialaccount.adapter import DefaultSocialAccountAdapter
from django.conf import settings
from django.core.exceptions import MultipleObjectsReturned
from allauth.socialaccount.models import SocialApp


class CustomAccountAdapter(DefaultAccountAdapter):
    """Custom adapter for account management"""
    
    def is_open_for_signup(self, request):
        return getattr(settings, 'ACCOUNT_ALLOW_REGISTRATION', True)
    
    def save_user(self, request, user, form, commit=True):
        """Save user and ensure profile is created"""
        user = super().save_user(request, user, form, commit=False)
        
        # Ensure display_name is set
        if not user.display_name:
            user.display_name = user.username
        
        if commit:
            user.save()
            # Profile will be created by signal
        
        return user


class CustomSocialAccountAdapter(DefaultSocialAccountAdapter):
    """Custom adapter for social account authentication"""
    
    def is_open_for_signup(self, request, sociallogin):
        return getattr(settings, 'ACCOUNT_ALLOW_REGISTRATION', True)
    
    def get_app(self, request, provider, client_id=None):
        """
        Override to handle multiple apps gracefully
        """
        try:
            return super().get_app(request, provider, client_id)
        except MultipleObjectsReturned:
            # If multiple apps found, get the first one
            # This shouldn't happen in production, but handles the error gracefully
            if client_id:
                app = SocialApp.objects.filter(
                    provider=provider,
                    client_id=client_id
                ).first()
            else:
                app = SocialApp.objects.filter(provider=provider).first()
            
            if not app:
                raise
            return app
    
    def populate_user(self, request, sociallogin, data):
        """Populate user instance from social provider data"""
        user = super().populate_user(request, sociallogin, data)
        
        # Get extra data from provider
        extra_data = sociallogin.account.extra_data
        
        # Set display name from Google
        if not user.display_name:
            user.display_name = extra_data.get('name', '') or user.username
        
        # Email is already set by allauth
        return user
    
    def save_user(self, request, sociallogin, form=None):
        """Save user from social login"""
        user = super().save_user(request, sociallogin, form)
        
        # Ensure profile exists (created by signal, but double-check)
        from .models import Profile
        Profile.objects.get_or_create(user=user)
        
        return user
    
    def pre_social_login(self, request, sociallogin):
        """
        Invoked just after a user successfully authenticates via a social provider,
        but before the login is actually processed.
        
        This allows us to connect existing accounts.
        """
        # If user is already logged in, connect the social account
        if request.user.is_authenticated:
            return
        
        # Check if user already exists with this email
        try:
            email = sociallogin.account.extra_data.get('email')
            if email:
                from django.contrib.auth import get_user_model
                User = get_user_model()
                user = User.objects.get(email=email)
                
                # Connect this social account to the existing user
                sociallogin.connect(request, user)
        except User.DoesNotExist:
            pass
        except Exception:
            # Log but don't fail on connection errors
            pass