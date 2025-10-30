from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.contrib.auth.tokens import default_token_generator
from django.utils.encoding import force_bytes, force_str
from accounts.models import EmailVerificationCode, Follow, Profile

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


class ProfileSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()
    
    class Meta:
        model = Profile
        fields = [
            'bio', 'website', 'location', 'phone', 
            'is_private', 'gender', 'birthday', 'avatar'
        ]
    
    def get_avatar(self, obj):
        if obj.avatar:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.avatar.url)
            return obj.avatar.url
        return None


class ProfileUpdateSerializer(serializers.ModelSerializer):
    avatar = serializers.ImageField(required=False, allow_null=True)
    
    class Meta:
        model = Profile
        fields = ['bio', 'website', 'location', 'phone', 'is_private',
                  'gender', 'birthday', 'avatar']   
        extra_kwargs = {
            'avatar': {'required': False},
        }

         

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
    profile = ProfileUpdateSerializer(required=False)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'display_name',
            # 'is_private',
              'verified', 'created_at', 
            'followers_count',
            'following_count', 'is_following',
              'profile'
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
    profile = ProfileUpdateSerializer(required=False)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'display_name', 
            'verified', 'created_at', 'last_seen',
            'followers_count', 'following_count', 'posts_count', 'is_following',
            'profile'
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
    

class UserUpdateSerializer(serializers.ModelSerializer):
    """
    User update serializer with nested profile updates
    Used for PATCH/PUT requests
    """
    profile = ProfileUpdateSerializer(required=False)

    class Meta:
        model = User
        fields = ['display_name', 'profile']
    
    def validate_display_name(self, value):
        """Validate display name"""
        if value and len(value.strip()) < 2:
            raise serializers.ValidationError(
                "Display name must be at least 2 characters long."
            )
        return value.strip() if value else value
    
    def update(self, instance, validated_data):
        """Update user and profile data"""
        profile_data = validated_data.pop('profile', None)
        
        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update or create profile
        if profile_data:
            profile, created = Profile.objects.get_or_create(user=instance)
            
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            
            profile.save()
        
        return instance
    
    def to_representation(self, instance):
        """Return full profile data after update"""
        serializer = UserProfileSerializer(
            instance, 
            context=self.context
        )
        return serializer.data

class PasswordResetRequestSerializer(serializers.Serializer):
    """Request password reset email"""
    email = serializers.EmailField()
    
    def validate_email(self, value):
        try:
            user = User.objects.get(email=value.lower())
        except User.DoesNotExist:
            # Don't reveal that email doesn't exist (security)
            pass
        return value.lower()
    
    def save(self):
        email = self.validated_data['email']
        try:
            user = User.objects.get(email=email)
            # Generate token and uid
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            
            # Send email via Celery
            from .tasks import send_password_reset_email
            send_password_reset_email.delay(user.id, uid, token)
            
            return {'uid': uid, 'token': token}
        except User.DoesNotExist:
            # Still return success to not reveal user existence
            return None

class UserSearchSerializer(serializers.ModelSerializer):
    """Serializer for user search results"""
    avatar = serializers.SerializerMethodField()
    full_name = serializers.CharField(source='full_name', read_only=True)
    bio = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'display_name',
            'full_name',
            'avatar',
            'bio',
            'verified',
            'auth_provider'
        ]
    
    def get_avatar(self, obj):
        """Get user's avatar URL from profile"""
        try:
            if hasattr(obj, 'profile') and obj.profile.avatar:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(obj.profile.avatar.url)
            return None
        except Exception:
            return None
    
    def get_bio(self, obj):
        """Get user's bio from profile"""
        try:
            if hasattr(obj, 'profile'):
                return obj.profile.bio
            return None
        except Exception:
            return None

class PasswordResetConfirmSerializer(serializers.Serializer):
    """Confirm password reset with token"""
    uid = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(write_only=True)
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {"new_password": "Passwords don't match"}
            )
        
        try:
            uid = force_str(urlsafe_base64_decode(attrs['uid']))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            raise serializers.ValidationError({"uid": "Invalid user ID"})
        
        if not default_token_generator.check_token(user, attrs['token']):
            raise serializers.ValidationError({"token": "Invalid or expired token"})
        
        attrs['user'] = user
        return attrs
    
    def save(self):
        user = self.validated_data['user']
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user


class ChangePasswordSerializer(serializers.Serializer):
    """Change password while logged in"""
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(
        write_only=True,
        validators=[validate_password]
    )
    new_password_confirm = serializers.CharField(write_only=True)
    
    def validate_old_password(self, value):
        user = self.context['request'].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect")
        return value
    
    def validate(self, attrs):
        if attrs['new_password'] != attrs['new_password_confirm']:
            raise serializers.ValidationError(
                {"new_password": "Passwords don't match"}
            )
        return attrs
    
    def save(self):
        user = self.context['request'].user
        user.set_password(self.validated_data['new_password'])
        user.save()
        return user

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


# class EmailChangeSerializer(serializers.Serializer):
#     new_email = serializers.EmailField(required=True)
#     password = serializers.CharField(required=False, write_only=True)
    
#     def validate_new_email(self, value):
#         """Check if email is already in use"""
#         if User.objects.filter(email=value).exists():
#             raise serializers.ValidationError("This email is already in use.")
#         return value
    
#     def validate(self, attrs):
#         user = self.context['request'].user
        
#         # If user registered with email, password is required
#         if user.auth_provider == 'email':
#             if not attrs.get('password'):
#                 raise serializers.ValidationError({
#                     "password": "Password is required to change email."
#                 })
            
#             # Verify password
#             if not user.check_password(attrs['password']):
#                 raise serializers.ValidationError({
#                     "password": "Incorrect password."
#                 })
        
#         return attrs


class EmailChangeRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    def validate_new_email(self, value):
        """Check if email is already in use"""
        user = self.context['request'].user
        
        if user.email == value:
            raise serializers.ValidationError("This is already your current email.")
        
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        
        return value
    
    def validate_password(self, value):
        """Verify user's password"""
        user = self.context['request'].user
        
        if not user.check_password(value):
            raise serializers.ValidationError("Incorrect password.")
        
        return value



class EmailVerificationCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = EmailVerificationCode
        fields = ['id', 'user', 'code', 'created_at', 'expires_at']
        read_only_fields = ['id', 'created_at', 'expires_at']

class EmailVerificationSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=6, min_length=6, required=True)
    
    def validate_code(self, value):
        """Validate the code format"""
        if not value.isdigit():
            raise serializers.ValidationError("Code must be 6 digits.")
        return value



class UserUpdateSerializer(serializers.ModelSerializer):
    profile = ProfileUpdateSerializer()
    
    class Meta:
        model = User
        fields = ['username', 'display_name', 'profile']
    
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        
        # Update user fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update profile fields
        if profile_data:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()
        
        return instance


