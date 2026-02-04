import random
import string
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
import uuid


class UserManager(BaseUserManager):
    def create_user(self, email, username, password=None, **extra_fields):
        if not email:
            raise ValueError('Email is required')
        if not username:
            raise ValueError('Username is required')
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, email, username, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('email_verified', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        
        return self.create_user(email, username, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(
        primary_key=True, 
        default=uuid.uuid4, 
        editable=False,
        unique=True
    )
    username = models.CharField(max_length=50, unique=True, db_index=True)
    email = models.EmailField(unique=True, db_index=True)
    display_name = models.CharField(max_length=100, blank=True)
    
    # Authentication provider
    auth_provider = models.CharField(
        max_length=20, 
        default='email',
        choices=[('email', 'Email'), ('google', 'Google')]
    )
    
    # Verification status
    email_verified = models.BooleanField(default=False)
    
    # Django admin fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'
    REQUIRED_FIELDS = ['username']

    class Meta:
        db_table = 'users'
        ordering = ['-created_at']
    
    def __str__(self):
        return self.username
    
    @property
    def full_name(self):
        return self.display_name or self.username


class Profile(models.Model):
    """Extended user profile with additional information"""
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='profile',
        primary_key=True
    )
    
    # Profile info
    bio = models.TextField(max_length=500, blank=True)
    avatar = models.ImageField(upload_to='avatars/', blank=True, null=True)
    website = models.URLField(max_length=200, blank=True)
    
    # Location
    location = models.CharField(max_length=100, blank=True)
    
    # Privacy settings
    is_private = models.BooleanField(default=False)
    
    # Profile customization
    theme = models.CharField(
        max_length=20,
        choices=[('light', 'Light'), ('dark', 'Dark'), ('auto', 'Auto')],
        default='auto'
    )
    
    # Contact - for contact syncing feature
    phone = models.CharField(max_length=20, blank=True, null=True)
    
    # Optional fields
    birthday = models.DateField(null=True, blank=True)
    gender = models.CharField(
        max_length=20,
        choices=[('male', 'Male'), ('female', 'Female'), ('other', 'Other')],
        blank=True
    )
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'profiles'
    
    def __str__(self):
        return f"Profile of {self.user.username}"


class EmailVerificationCode(models.Model):
    """Store email verification codes for signup and email changes"""
    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='email_verification_codes'
    )
    # For initial signup verification, new_email will be empty
    # For email change verification, new_email will contain the new email
    new_email = models.EmailField(blank=True)
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'email_verification_codes'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'code']),
            models.Index(fields=['expires_at']),
        ]
    
    def save(self, *args, **kwargs):
        if not self.code:
            self.code = self.generate_code()
        if not self.expires_at:
            # Code expires in 15 minutes
            self.expires_at = timezone.now() + timezone.timedelta(minutes=15)
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_code():
        """Generate a 6-digit verification code"""
        return ''.join(random.choices(string.digits, k=6))
    
    def is_valid(self):
        """Check if code is still valid"""
        return (
            not self.is_used and 
            timezone.now() < self.expires_at and 
            self.attempts < 5  # Max 5 attempts
        )
    
    def __str__(self):
        email = self.new_email or self.user.email
        return f"{self.user.username} - {email} - {self.code}"


class PasswordResetToken(models.Model):
    """Store password reset tokens"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='password_reset_tokens'
    )
    token = models.CharField(max_length=64, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    
    class Meta:
        db_table = 'password_reset_tokens'
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.token:
            self.token = self.generate_token()
        if not self.expires_at:
            # Token expires in 1 hour
            self.expires_at = timezone.now() + timezone.timedelta(hours=1)
        super().save(*args, **kwargs)
    
    @staticmethod
    def generate_token():
        """Generate a secure random token"""
        return ''.join(random.choices(string.ascii_letters + string.digits, k=64))
    
    def is_valid(self):
        """Check if token is still valid"""
        return not self.is_used and timezone.now() < self.expires_at
    
    def __str__(self):
        return f"{self.user.username} - Reset Token"


class RefreshToken(models.Model):
    """Store refresh tokens for JWT authentication"""
    user = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='refresh_tokens'
    )
    token = models.CharField(max_length=255, unique=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_revoked = models.BooleanField(default=False)
    
    # Track device/session info
    device_info = models.CharField(max_length=255, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    
    class Meta:
        db_table = 'refresh_tokens'
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.expires_at:
            # Refresh token expires in 30 days
            self.expires_at = timezone.now() + timezone.timedelta(days=30)
        super().save(*args, **kwargs)
    
    def is_valid(self):
        """Check if token is still valid"""
        return not self.is_revoked and timezone.now() < self.expires_at
    
    def __str__(self):
        return f"{self.user.username} - Refresh Token"