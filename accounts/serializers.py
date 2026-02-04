# serializers.py
from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from accounts.models import EmailVerificationCode, Profile

User = get_user_model()


class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    """Custom JWT serializer that accepts username or email"""
    username_field = 'login'
    
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['login'] = serializers.CharField()
        self.fields.pop('username', None)
    
    def validate(self, attrs):
        login = attrs.get('login')
        password = attrs.get('password')
        
        # Try to find user by username or email
        user = None
        if '@' in login:
            try:
                user = User.objects.get(email=login)
            except User.DoesNotExist:
                pass
        else:
            try:
                user = User.objects.get(username=login)
            except User.DoesNotExist:
                pass
        
        if user is None:
            raise serializers.ValidationError('No account found with these credentials')
        
        if not user.check_password(password):
            raise serializers.ValidationError('Invalid credentials')
        
        if not user.is_active:
            raise serializers.ValidationError('User account is disabled')
        
        refresh = self.get_token(user)
        
        data = {
            'refresh': str(refresh),
            'access': str(refresh.access_token),
            'user': UserSerializer(user).data
        }
        
        return data


class ProfileSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['bio', 'avatar', 'phone', 'location', 'is_private']
        

class UserSerializer(serializers.ModelSerializer):
    profile = ProfileSerializer(read_only=True)

    class Meta:
        model = User
        fields = [
            'id', 'username', 'email', 'display_name',
            'email_verified', 'created_at', 'last_seen', 'profile'
        ]
        read_only_fields = ['id', 'created_at']


class UserRegistrationSerializer(serializers.ModelSerializer):
    password = serializers.CharField(
        write_only=True, 
        validators=[validate_password],
        style={'input_type': 'password'}
    )
    password_confirm = serializers.CharField(
        write_only=True,
        style={'input_type': 'password'}
    )
    
    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'password_confirm', 'display_name']
        extra_kwargs = {
            'display_name': {'required': False}
        }
    
    def validate_username(self, value):
        if '@' in value:
            raise serializers.ValidationError("Username cannot contain @ symbol")
        
        if len(value) < 3:
            raise serializers.ValidationError("Username must be at least 3 characters long")
        
        if not value.replace('_', '').replace('.', '').isalnum():
            raise serializers.ValidationError(
                "Username can only contain letters, numbers, underscores, and periods"
            )
        
        return value.lower()
    
    def validate_email(self, value):
        return value.lower()
    
    def validate(self, attrs):
        if attrs['password'] != attrs['password_confirm']:
            raise serializers.ValidationError({
                "password_confirm": "Passwords don't match"
            })
        return attrs
    
    def create(self, validated_data):
        validated_data.pop('password_confirm')
        password = validated_data.pop('password')
        
        user = User.objects.create_user(
            username=validated_data['username'],
            email=validated_data['email'],
            password=password,
            display_name=validated_data.get('display_name', '')
        )
        
        return user


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Profile
        fields = ['bio', 'avatar', 'phone', 'location', 'is_private', 'gender', 'website', 'birthday']


class UserProfileUpdateSerializer(serializers.ModelSerializer):
    profile = ProfileUpdateSerializer()
    
    class Meta:
        model = User
        fields = ['username', 'display_name', 'profile']
    
    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', None)
        
        # Update User fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update Profile fields
        if profile_data:
            profile, _ = Profile.objects.get_or_create(user=instance)
            for attr, value in profile_data.items():
                setattr(profile, attr, value)
            profile.save()
        
        return instance
    
class AvatarUpdateSerializer(serializers.ModelSerializer):
    # This maps the field directly to the nested profile
    avatar = serializers.ImageField(source='profile.avatar', allow_null=True)

    class Meta:
        model = User
        fields = ['avatar']

    def update(self, instance, validated_data):
        profile_data = validated_data.pop('profile', {})
        avatar = profile_data.get('avatar')

        profile, _ = Profile.objects.get_or_create(user=instance)
        profile.avatar = avatar # This handles both file upload and 'None' for delete
        profile.save()
        return instance


class PasswordResetRequestSerializer(serializers.Serializer):
    email = serializers.EmailField()
    
    def validate_email(self, value):
        return value.lower()


class PasswordResetConfirmSerializer(serializers.Serializer):
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
        return attrs


class ChangePasswordSerializer(serializers.Serializer):
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


class EmailChangeRequestSerializer(serializers.Serializer):
    new_email = serializers.EmailField(required=True)
    password = serializers.CharField(required=True, write_only=True)
    
    def validate_new_email(self, value):
        user = self.context['request'].user
        
        if user.email == value:
            raise serializers.ValidationError("This is already your current email.")
        
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError("This email is already in use.")
        
        return value
    
    def validate_password(self, value):
        user = self.context['request'].user
        
        if not user.check_password(value):
            raise serializers.ValidationError("Incorrect password.")
        
        return value


class EmailVerificationSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=6, min_length=6, required=True)
    
    def validate_code(self, value):
        if not value.isdigit():
            raise serializers.ValidationError("Code must be 6 digits.")
        return value


class UserSearchSerializer(serializers.ModelSerializer):
    avatar = serializers.SerializerMethodField()
    bio = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = [
            'id',
            'username',
            'display_name',
            'avatar',
            'bio',
            'email_verified'
        ]
    
    def get_avatar(self, obj):
        try:
            if hasattr(obj, 'profile') and obj.profile.avatar:
                request = self.context.get('request')
                if request:
                    return request.build_absolute_uri(obj.profile.avatar.url)
            return None
        except Exception:
            return None
    
    def get_bio(self, obj):
        try:
            if hasattr(obj, 'profile'):
                return obj.profile.bio
            return None
        except Exception:
            return None