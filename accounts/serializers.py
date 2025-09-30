from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password

from accounts.models import Follow

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT serializer that accepts username or email"""
    username_field = 'login'  # Changed from 'username'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Remove the default username field and add our custom login field
        self.fields['login'] = serializers.CharField()
        self.fields.pop('username', None)
    
    def validate(self, attrs):
        # Get the login credential (can be username or email)
        login = attrs.get('login')
        password = attrs.get('password')
        
        # Try to find user by username or email
        user = None
        if '@' in login:
            # Looks like an email
            try:
                user = User.objects.get(email=login)
            except User.DoesNotExist:
                pass
        else:
            # Looks like a username
            try:
                user = User.objects.get(username=login)
            except User.DoesNotExist:
                pass
        
        if user is None:
            raise serializers.ValidationError('No account found with these credentials')
        
        # Check password
        if not user.check_password(password):
            raise serializers.ValidationError('Invalid credentials')
        
        if not user.is_active:
            raise serializers.ValidationError('User account is disabled')
        
        # Generate tokens using the parent class logic
        refresh = self.get_token(user)
        
        data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
        }
        
        return data


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, validators=[validate_password])
    password_confirm = serializers.CharField(write_only=True)
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm', 'display_name']
    
    def validate_username(self, value):
        """Ensure username doesn't contain @ symbol"""
        if '@' in value:
            raise serializers.ValidationError("Username cannot contain @ symbol")
        return value.lower()
    
    def validate_email(self, value):
        """Normalize email to lowercase"""
        return value.lower()
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({"password": "Passwords don't match"})
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        user = User.objects.create_user(**validated_data)
        return user


class UserSerializer(serializers.ModelSerializer):
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'display_name', 'bio', 'avatar',
            'is_private', 'verified', 'created_at', 'followers_count',
            'following_count', 'is_following'
        ]
        read_only_fields = ['id', 'created_at', 'verified']
    
    def get_followers_count(self, obj):
        return obj.followers.count()
    
    def get_following_count(self, obj):
        return obj.following.count()
    
    def get_is_following(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.followers.filter(follower=request.user).exists()
        return False


class UserProfileSerializer(serializers.ModelSerializer):
    """Detailed profile serializer"""
    followers_count = serializers.SerializerMethodField()
    following_count = serializers.SerializerMethodField()
    posts_count = serializers.SerializerMethodField()
    is_following = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'display_name', 'bio', 'avatar',
            'is_private', 'verified', 'created_at', 'last_seen',
            'followers_count', 'following_count', 'posts_count', 'is_following'
        ]
        read_only_fields = ['id', 'created_at', 'verified', 'last_seen']
    
    def get_followers_count(self, obj):
        return obj.followers.count()
    
    def get_following_count(self, obj):
        return obj.following.count()
    
    def get_posts_count(self, obj):
        return obj.posts.count()
    
    def get_is_following(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return obj.followers.filter(follower=request.user).exists()
        return False


class FollowToggleSerializer(serializers.Serializer):
    """Serializer for follow/unfollow responses"""
    message = serializers.CharField(read_only=True)
    following = serializers.BooleanField(read_only=True)
    
    class Meta:
        fields = ['message', 'following']

class FollowSerializer(serializers.ModelSerializer):
    """Serializer for Follow model instances"""
    follower_username = serializers.CharField(source='follower.username', read_only=True)
    followee_username = serializers.CharField(source='followee.username', read_only=True)
    
    class Meta:
        model = Follow
        fields = ['id', 'follower', 'follower_username', 'followee', 'followee_username', 'created_at']
        read_only_fields = ['id', 'created_at']

class UserUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['display_name', 'bio', 'avatar', 'is_private']