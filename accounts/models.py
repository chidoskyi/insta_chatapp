import random
import string
from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone
import uuid


class UserManager(BaseUserManager):
    def create_user(self, username, email, password=None, **extra_fields):
        if not username:
            raise ValueError('Username is required')
        if not email:
            raise ValueError('Email is required')
        
        email = self.normalize_email(email)
        user = self.model(username=username, email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user
    
    def create_superuser(self, username, email, password=None, **extra_fields):
        extra_fields.setdefault('is_staff', True)
        extra_fields.setdefault('is_superuser', True)
        extra_fields.setdefault('verified', True)
        
        if extra_fields.get('is_staff') is not True:
            raise ValueError('Superuser must have is_staff=True')
        if extra_fields.get('is_superuser') is not True:
            raise ValueError('Superuser must have is_superuser=True')
        
        return self.create_user(username, email, password, **extra_fields)


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
    auth_provider = models.CharField(
        max_length=20, 
        default='email',
        choices=[('email', 'Email'), ('google', 'Google')]
    )
    
    verified = models.BooleanField(default=False)
    
    # Django admin fields
    is_active = models.BooleanField(default=True)
    is_staff = models.BooleanField(default=False)
    email_verified = models.BooleanField(default=False)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    last_seen = models.DateTimeField(null=True, blank=True)
    
    objects = UserManager()
    
    USERNAME_FIELD = 'email'       # login field
    REQUIRED_FIELDS = ['username'] # other required fields

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
    
    # Contact
    phone = models.CharField(max_length=20, blank=True)
    
    # Birthday (optional)
    birthday = models.DateField(null=True, blank=True)
    
    # Gender (optional)
    GENDER_CHOICES = (
        ('male', 'Male'),
        ('female', 'Female')
    )
    gender = models.CharField(max_length=20, choices=GENDER_CHOICES, blank=True)
    
    # Denormalized counts for performance
    followers_count = models.PositiveIntegerField(default=0)
    following_count = models.PositiveIntegerField(default=0)
    posts_count = models.PositiveIntegerField(default=0)
    
    # Timestamps
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        db_table = 'profiles'
    
    def __str__(self):
        return f"Profile of {self.user.username}"
    
    def update_followers_count(self):
        """Update followers count from Follow model"""
        self.followers_count = self.user.followers.count()
        self.save(update_fields=['followers_count'])
    
    def update_following_count(self):
        """Update following count from Follow model"""
        self.following_count = self.user.following.count()
        self.save(update_fields=['following_count'])
    
    def update_posts_count(self):
        """Update posts count from Post model"""
        self.posts_count = self.user.posts.count()
        self.save(update_fields=['posts_count'])

class Follow(models.Model):
    follower = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='following'
    )
    followee = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='followers'
    )
    created_at = models.DateTimeField(default=timezone.now)
    
    class Meta:
        db_table = 'follows'
        unique_together = ('follower', 'followee')
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['followee', '-created_at']),
            models.Index(fields=['follower', '-created_at']),
        ]
    
    def __str__(self):
        return f"{self.follower.username} follows {self.followee.username}"
    

class EmailVerificationCode(models.Model):
    """Store email verification codes for email changes"""
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='email_verification_codes')
    new_email = models.EmailField()
    code = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    attempts = models.IntegerField(default=0)
    
    class Meta:
        db_table = 'email_verification_codes'
        ordering = ['-created_at']
    
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
        return f"{self.user.username} - {self.new_email} - {self.code}"