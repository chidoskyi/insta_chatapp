from profile import Profile
from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from allauth.socialaccount.models import SocialAccount
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from django.core.mail import send_mail
from django.conf import settings
from django.utils import timezone
from rest_framework.parsers import JSONParser, MultiPartParser, FormParser
from django.db.models import Q
from django.core.paginator import Paginator
import logging

User = get_user_model()
logger = logging.getLogger(__name__)

from drf_spectacular.utils import extend_schema
from .serializers import (
    ChangePasswordSerializer,
    CustomTokenObtainPairSerializer,
    EmailChangeRequestSerializer,
    EmailVerificationSerializer,
    FollowToggleSerializer,
    PasswordResetConfirmSerializer,
    PasswordResetRequestSerializer,
    UserRegistrationSerializer,
    UserSearchSerializer,
    UserSerializer,
    UserProfileSerializer,
    UserUpdateSerializer
)
from .models import EmailVerificationCode, Follow

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """Register a new user"""
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserRegistrationSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Save user with email auth provider
        user = serializer.save(auth_provider='email')
        
        # Generate JWT tokens
        refresh = RefreshToken.for_user(user)
        
        return Response({
            'user': UserSerializer(user).data,
            'tokens': {
                'refresh': str(refresh),
                'access': str(refresh.access_token),
            }
        }, status=status.HTTP_201_CREATED)


class CustomLoginView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer
    
    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        
        # You can add additional login tracking or logging here
        if response.status_code == 200:
            # Log successful login, update last_login, etc.
            print(f"User logged in successfully")  # Replace with proper logging
        
        return response

class EmailChangeRequestView(APIView):
    """
    Step 1: Request email change and send verification code
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        """Get user's email change capabilities"""
        user = request.user
        can_change = user.auth_provider == 'email'
        
        return Response({
            'can_change_email': can_change,
            'auth_provider': user.auth_provider,
            'current_email': user.email,
            'message': self._get_message(user.auth_provider),
            'instructions': self._get_instructions(user.auth_provider) if not can_change else None
        })
    
    def post(self, request):
        """Request email change - sends verification code"""
        user = request.user
        
        # Check if user can change email
        if user.auth_provider != 'email':
            return Response({
                'error': 'Email change not allowed',
                'message': self._get_message(user.auth_provider),
                'auth_provider': user.auth_provider,
                'instructions': self._get_instructions(user.auth_provider)
            }, status=status.HTTP_403_FORBIDDEN)
        
        # Validate request
        serializer = EmailChangeRequestSerializer(
            data=request.data, 
            context={'request': request}
        )
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        new_email = serializer.validated_data['new_email']
        
        # Invalidate any existing pending verification codes for this user
        EmailVerificationCode.objects.filter(
            user=user,
            is_used=False
        ).update(is_used=True)
        
        # Create new verification code
        verification = EmailVerificationCode.objects.create(
            user=user,
            new_email=new_email
        )
        
        # Send verification email
        try:
            self._send_verification_email(user, new_email, verification.code)
            
            return Response({
                'message': 'Verification code sent to your new email address',
                'new_email': new_email,
                'expires_in_minutes': 15,
                'note': 'Please check your email and enter the 6-digit code to verify'
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            # Delete the verification code if email fails
            verification.delete()
            return Response({
                'error': 'Failed to send verification email',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _send_verification_email(self, user, new_email, code):
        """Send verification code email"""
        subject = 'Verify Your New Email Address'
        message = f"""
Hello {user.display_name or user.username},

You requested to change your email address to {new_email}.

Your verification code is: {code}

This code will expire in 15 minutes.

If you didn't request this change, please ignore this email and secure your account.

Best regards,
Your App Team
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[new_email],
            fail_silently=False,
        )
    
    def _get_message(self, auth_provider):
        """Get appropriate message based on auth provider"""
        if auth_provider == 'google':
            return "Email cannot be changed here because you signed in with Google"
        elif auth_provider == 'email':
            return "You can change your email address"
        return "Email change not available for this authentication method"
    
    def _get_instructions(self, auth_provider):
        """Get instructions for changing email with OAuth providers"""
        instructions = {
            'google': {
                'title': 'To change your email with Google OAuth',
                'steps': [
                    'Visit your Google Account settings at https://myaccount.google.com',
                    'Update your primary email address',
                    'Log out and log back in to this app to sync the changes'
                ],
                'note': 'The email change will automatically sync when you next log in'
            }
        }
        return instructions.get(auth_provider, {})


# class EmailChangeView(APIView):
#     """
#     Handle email change requests with auth provider checks
#     """
#     permission_classes = [permissions.IsAuthenticated]
    
#     def get(self, request):
#         """Get user's email change capabilities"""
#         user = request.user
        
#         can_change = user.auth_provider == 'email'
        
#         return Response({
#             'can_change_email': can_change,
#             'auth_provider': user.auth_provider,
#             'current_email': user.email,
#             'message': self._get_message(user.auth_provider)
#         })
    
#     def post(self, request):
#         """Change user email"""
#         user = request.user
        
#         # Check if user can change email
#         if user.auth_provider != 'email':
#             return Response({
#                 'error': 'Email change not allowed',
#                 'message': self._get_message(user.auth_provider),
#                 'auth_provider': user.auth_provider,
#                 'instructions': self._get_instructions(user.auth_provider)
#             }, status=status.HTTP_403_FORBIDDEN)
        
#         # Validate and change email
#         serializer = EmailChangeSerializer(
#             data=request.data, 
#             context={'request': request}
#         )
        
#         if serializer.is_valid():
#             new_email = serializer.validated_data['new_email']
#             old_email = user.email
            
#             # Update email
#             user.email = new_email
#             user.email_verified = False  # Require re-verification
#             user.save()
            
#             # Optional: Send verification email
#             # self._send_verification_email(user, new_email)
            
#             return Response({
#                 'message': 'Email changed successfully',
#                 'old_email': old_email,
#                 'new_email': new_email,
#                 'email_verified': False,
#                 'note': 'Please verify your new email address'
#             }, status=status.HTTP_200_OK)
        
#         return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
    
#     def _get_message(self, auth_provider):
#         """Get appropriate message based on auth provider"""
#         if auth_provider == 'google':
#             return "Email cannot be changed here because you signed in with Google"
#         elif auth_provider == 'email':
#             return "You can change your email address"
#         return "Email change not available for this authentication method"
    
#     def _get_instructions(self, auth_provider):
#         """Get instructions for changing email with OAuth providers"""
#         instructions = {
#             'google': {
#                 'title': 'To change your email with Google OAuth',
#                 'steps': [
#                     'Visit your Google Account settings at https://myaccount.google.com',
#                     'Update your primary email address',
#                     'Log out and log back in to this app to sync the changes'
#                 ],
#                 'note': 'The email change will automatically sync when you next log in'
#             }
#         }
#         return instructions.get(auth_provider, {})



class EmailVerificationView(APIView):
    """
    Step 2: Verify the code and complete email change
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Verify code and change email"""
        user = request.user
        
        serializer = EmailVerificationSerializer(data=request.data)
        
        if not serializer.is_valid():
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)
        
        code = serializer.validated_data['code']
        
        try:
            # Get the most recent unused verification code for this user
            verification = EmailVerificationCode.objects.filter(
                user=user,
                is_used=False
            ).order_by('-created_at').first()
            
            if not verification:
                return Response({
                    'error': 'No pending email change request found',
                    'detail': 'Please request a new email change'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Check if code is still valid
            if not verification.is_valid():
                reason = 'expired' if timezone.now() >= verification.expires_at else 'too many attempts'
                return Response({
                    'error': f'Verification code {reason}',
                    'detail': 'Please request a new email change'
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Increment attempts
            verification.attempts += 1
            verification.save()
            
            # Verify the code
            if verification.code != code:
                remaining_attempts = 5 - verification.attempts
                
                if remaining_attempts <= 0:
                    verification.is_used = True
                    verification.save()
                    return Response({
                        'error': 'Maximum verification attempts exceeded',
                        'detail': 'Please request a new email change'
                    }, status=status.HTTP_400_BAD_REQUEST)
                
                return Response({
                    'error': 'Invalid verification code',
                    'remaining_attempts': remaining_attempts
                }, status=status.HTTP_400_BAD_REQUEST)
            
            # Code is correct - update email
            old_email = user.email
            new_email = verification.new_email
            
            user.email = new_email
            user.email_verified = True
            user.save()
            
            # Mark verification as used
            verification.is_used = True
            verification.save()
            
            # Optional: Send confirmation email to old address
            self._send_confirmation_email(user, old_email, new_email)
            
            return Response({
                'message': 'Email changed successfully',
                'old_email': old_email,
                'new_email': new_email,
                'email_verified': True
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            return Response({
                'error': 'An error occurred during verification',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _send_confirmation_email(self, user, old_email, new_email):
        """Send confirmation to old email address"""
        try:
            subject = 'Email Address Changed'
            message = f"""
Hello {user.display_name or user.username},

Your email address has been successfully changed from {old_email} to {new_email}.

If you didn't make this change, please contact support immediately.

Best regards,
Your App Team
            """
            
            send_mail(
                subject=subject,
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[old_email],
                fail_silently=True,  # Don't fail if old email is no longer accessible
            )
        except:
            pass  # Silently fail if confirmation email can't be sent


class ResendVerificationCodeView(APIView):
    """
    Resend verification code if expired or lost
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        """Resend verification code"""
        user = request.user
        
        # Get the most recent verification request
        verification = EmailVerificationCode.objects.filter(
            user=user,
            is_used=False
        ).order_by('-created_at').first()
        
        if not verification:
            return Response({
                'error': 'No pending email change request found',
                'detail': 'Please start a new email change request'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Check if last code was sent less than 1 minute ago (rate limiting)
        if timezone.now() < verification.created_at + timezone.timedelta(minutes=1):
            return Response({
                'error': 'Please wait before requesting a new code',
                'detail': 'You can request a new code in 1 minute'
            }, status=status.HTTP_429_TOO_MANY_REQUESTS)
        
        # Create new verification code
        new_verification = EmailVerificationCode.objects.create(
            user=user,
            new_email=verification.new_email
        )
        
        # Mark old one as used
        verification.is_used = True
        verification.save()
        
        # Send new code
        try:
            self._send_verification_email(user, new_verification.new_email, new_verification.code)
            
            return Response({
                'message': 'New verification code sent',
                'new_email': new_verification.new_email,
                'expires_in_minutes': 15
            }, status=status.HTTP_200_OK)
            
        except Exception as e:
            new_verification.delete()
            return Response({
                'error': 'Failed to send verification email',
                'detail': str(e)
            }, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def _send_verification_email(self, user, new_email, code):
        """Send verification code email"""
        subject = 'Verify Your New Email Address'
        message = f"""
Hello {user.display_name or user.username},

You requested to change your email address to {new_email}.

Your verification code is: {code}

This code will expire in 15 minutes.

If you didn't request this change, please ignore this email and secure your account.

Best regards,
Your App Team
        """
        
        send_mail(
            subject=subject,
            message=message,
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[new_email],
            fail_silently=False,
        )


# Update GoogleLoginView to set auth_provider
class GoogleLoginView(APIView):
    """
    Custom Google OAuth2 login that bypasses dj-rest-auth
    """
    permission_classes = []
    authentication_classes = []
    
    def post(self, request):
        code = request.data.get('code')
        
        if not code:
            return Response(
                {'error': 'Authorization code is required'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get Google OAuth credentials
        from decouple import config
        client_id = config('GOOGLE_OAUTH_CLIENT_ID')
        client_secret = config('GOOGLE_OAUTH_CLIENT_SECRET')
        redirect_uri = config('GOOGLE_OAUTH_CALLBACK_URL', default='http://localhost:3000/auth/google/callback')
        
        # Exchange authorization code for access token
        token_url = 'https://oauth2.googleapis.com/token'
        token_data = {
            'code': code,
            'client_id': client_id,
            'client_secret': client_secret,
            'redirect_uri': redirect_uri,
            'grant_type': 'authorization_code',
        }
        
        try:
            import requests
            from rest_framework_simplejwt.tokens import RefreshToken
            
            # Get access token
            token_response = requests.post(token_url, data=token_data)
            token_response.raise_for_status()
            tokens = token_response.json()
            access_token = tokens.get('access_token')
            
            if not access_token:
                return Response(
                    {'error': 'Failed to get access token from Google'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Get user info from Google
            user_info_url = 'https://www.googleapis.com/oauth2/v2/userinfo'
            headers = {'Authorization': f'Bearer {access_token}'}
            user_response = requests.get(user_info_url, headers=headers)
            user_response.raise_for_status()
            user_data = user_response.json()
            
            email = user_data.get('email')
            google_id = user_data.get('id')
            name = user_data.get('name', '')
            
            if not email or not google_id:
                return Response(
                    {'error': 'Failed to get user information from Google'}, 
                    status=status.HTTP_400_BAD_REQUEST
                )
            
            # Find or create user
            user = None
            created = False
            
            try:
                # Check if social account exists
                social_account = SocialAccount.objects.get(
                    provider='google',
                    uid=google_id
                )
                user = social_account.user
                
                # Update email if changed in Google account
                if user.email != email:
                    user.email = email
                    user.save()
                
            except SocialAccount.DoesNotExist:
                # Check if user with email exists
                try:
                    user = User.objects.get(email=email)
                    # Update auth_provider to google if they're linking
                    if user.auth_provider == 'email':
                        user.auth_provider = 'google'
                        user.email_verified = True
                        user.save()
                except User.DoesNotExist:
                    # Create new user
                    username = email.split('@')[0]
                    base_username = username
                    counter = 1
                    
                    # Ensure username is unique
                    while User.objects.filter(username=username).exists():
                        username = f"{base_username}{counter}"
                        counter += 1
                    
                    user = User.objects.create_user(
                        username=username,
                        email=email,
                        display_name=name or username,
                        auth_provider='google',  # Set auth provider
                        email_verified=True  # Google emails are verified
                    )
                    created = True
                
                # Create social account link
                SocialAccount.objects.create(
                    user=user,
                    provider='google',
                    uid=google_id,
                    extra_data=user_data
                )
            
            # Ensure profile exists
            from accounts.models import Profile
            profile, profile_created = Profile.objects.get_or_create(user=user)
            
            # Generate JWT tokens
            refresh = RefreshToken.for_user(user)
            
            return Response({
                'user': {
                    'id': user.id,
                    'username': user.username,
                    'email': user.email,
                    'display_name': user.display_name,
                    'auth_provider': user.auth_provider,
                    'profile': {
                        'bio': profile.bio,
                        'avatar': request.build_absolute_uri(profile.avatar.url) if profile.avatar else None,
                    }
                },
                'tokens': {
                    'access': str(refresh.access_token),
                    'refresh': str(refresh),
                }
            }, status=status.HTTP_200_OK)
            
        except requests.RequestException as e:
            return Response(
                {'error': f'Failed to authenticate with Google: {str(e)}'}, 
                status=status.HTTP_400_BAD_REQUEST
            )
        except Exception as e:
            import traceback
            print(traceback.format_exc())
            return Response(
                {'error': f'An error occurred: {str(e)}'}, 
                status=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
 

class PasswordResetRequestView(APIView):
    """Request password reset email"""
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = PasswordResetRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({
            'message': 'If an account exists with this email, you will receive password reset instructions.'
        })


class PasswordResetConfirmView(APIView):
    """Confirm password reset with token"""
    permission_classes = [permissions.AllowAny]
    
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({
            'message': 'Password has been reset successfully. You can now login with your new password.'
        })


class ChangePasswordView(APIView):
    """Change password while logged in"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request):
        serializer = ChangePasswordSerializer(
            data=request.data,
            context={'request': request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        return Response({
            'message': 'Password changed successfully'
        })

class UserProfileView(generics.RetrieveUpdateAPIView):
    """Get or update user profile"""
    queryset = User.objects.all()
    lookup_field = 'username'
    
    def get_serializer_class(self):
        if self.request.method == 'GET':
            return UserProfileSerializer
        return UserUpdateSerializer
    
    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.IsAuthenticatedOrReadOnly()]
        return [permissions.IsAuthenticated()]
    
    def update(self, request, *args, **kwargs):
        user = self.get_object()
        if user != request.user:
            return Response(
                {'error': 'You can only update your own profile'},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)


class FollowToggleView(APIView):
    """Follow or unfollow a user"""
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = FollowToggleSerializer  # This fixes the schema warning
    
    def post(self, request, username):
        followee = get_object_or_404(User, username=username)
        
        if followee == request.user:
            return Response(
                {'error': 'You cannot follow yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        follow, created = Follow.objects.get_or_create(
            follower=request.user,
            followee=followee
        )
        
        if not created:
            follow.delete()
            return Response({
                'message': f'Unfollowed {username}',
                'following': False
            })
        
        return Response({
            'message': f'Following {username}',
            'following': True
        }, status=status.HTTP_201_CREATED)


class FollowersListView(generics.ListAPIView):
    """List followers of a user"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        username = self.kwargs.get('username')
        user = get_object_or_404(User, username=username)
        
        # Get follower IDs and fetch users
        follower_ids = user.followers.values_list('follower_id', flat=True)
        return User.objects.filter(id__in=follower_ids)


class FollowingListView(generics.ListAPIView):
    """List users that a user is following"""
    serializer_class = UserSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        username = self.kwargs.get('username')
        user = get_object_or_404(User, username=username)
        
        # Get followee IDs and fetch users
        followee_ids = user.following.values_list('followee_id', flat=True)
        return User.objects.filter(id__in=followee_ids)

class UserProfileByUsernameView(generics.RetrieveAPIView):
    """
    Get user profile by username (for viewing other users)
    READ ONLY - Use this to view any user's profile
    """
    serializer_class = UserProfileSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    lookup_field = 'username'
    lookup_url_kwarg = 'username'
    
    def get_queryset(self):
        return User.objects.filter(is_active=True).select_related('profile')
    
    def retrieve(self, request, *args, **kwargs):
        username = self.kwargs.get('username')
        user = get_object_or_404(User, username=username, is_active=True)
        
        # Ensure profile exists
        Profile.objects.get_or_create(user=user)
        
        serializer = self.get_serializer(user)
        return Response(serializer.data)


class UserProfileByIdView(generics.RetrieveUpdateAPIView):
    """
    Get or update user profile by ID
    Use this for the logged-in user to update their own profile
    """
    queryset = User.objects.all()
    lookup_field = 'id'
    
    def get_serializer_class(self):
        if self.request.method == 'GET':
            return UserProfileSerializer
        return UserUpdateSerializer
    
    def get_permissions(self):
        if self.request.method == 'GET':
            return [permissions.IsAuthenticatedOrReadOnly()]
        return [permissions.IsAuthenticated()]
    
    def retrieve(self, request, *args, **kwargs):
        user_id = self.kwargs.get('id')
        user = get_object_or_404(User, id=user_id, is_active=True)
        
        # Ensure profile exists
        Profile.objects.get_or_create(user=user)
        
        serializer = self.get_serializer(user)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        user_id = self.kwargs.get('id')
        user = get_object_or_404(User, id=user_id)
        
        # Check if user is updating their own profile
        if str(user.id) != str(request.user.id):
            return Response(
                {'error': 'You can only update your own profile'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        # Ensure profile exists
        Profile.objects.get_or_create(user=user)
        
        # Convert profile[field] syntax to nested structure
        processed_data = {}
        profile_data = {}
        
        # Process regular data fields
        for key, value in request.data.items():
            if key.startswith('profile[') and key.endswith(']'):
                field_name = key[8:-1]
                profile_data[field_name] = value
            else:
                processed_data[key] = value
        
        # Process file fields
        for key, file_obj in request.FILES.items():
            if key.startswith('profile[') and key.endswith(']'):
                field_name = key[8:-1]
                profile_data[field_name] = file_obj
            else:
                processed_data[key] = file_obj
        
        # Add the nested profile data
        if profile_data:
            processed_data['profile'] = profile_data
        
        logger.info(f"Processed data structure: {processed_data}")
        
        # Create serializer with processed data
        serializer = self.get_serializer(user, data=processed_data, partial=True)
        
        if serializer.is_valid():
            logger.info("Serializer is valid, saving...")
            serializer.save()
            return Response(serializer.data)
        else:
            logger.error(f"Serializer errors: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class CurrentUserProfileView(generics.RetrieveUpdateAPIView):
    """
    Get or update the currently logged-in user's profile
    Endpoint: /api/users/me/
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get_serializer_class(self):
        if self.request.method == 'GET':
            return UserProfileSerializer
        return UserUpdateSerializer
    
    def get_object(self):
        # Always return the currently authenticated user
        user = self.request.user
        # Ensure profile exists
        Profile.objects.get_or_create(user=user)
        return user
    
    def retrieve(self, request, *args, **kwargs):
        user = self.get_object()
        serializer = self.get_serializer(user)
        return Response(serializer.data)
    
    def update(self, request, *args, **kwargs):
        user = self.get_object()
        
        # Convert profile[field] syntax to nested structure
        processed_data = {}
        profile_data = {}
        
        # Process regular data fields
        for key, value in request.data.items():
            if key.startswith('profile[') and key.endswith(']'):
                field_name = key[8:-1]
                profile_data[field_name] = value
            else:
                processed_data[key] = value
        
        # Process file fields
        for key, file_obj in request.FILES.items():
            if key.startswith('profile[') and key.endswith(']'):
                field_name = key[8:-1]
                profile_data[field_name] = file_obj
            else:
                processed_data[key] = file_obj
        
        # Add the nested profile data
        if profile_data:
            processed_data['profile'] = profile_data
        
        logger.info(f"Processed data structure: {processed_data}")
        
        serializer = self.get_serializer(user, data=processed_data, partial=True)
        
        if serializer.is_valid():
            logger.info("Serializer is valid, saving...")
            serializer.save()
            return Response(serializer.data)
        else:
            logger.error(f"Serializer errors: {serializer.errors}")
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)



@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_user(request):
    """Get current authenticated user"""
    serializer = UserProfileSerializer(request.user, context={'request': request})
    return Response(serializer.data)

class UserSearchView(APIView):
    """
    Search users by username or display name
    
    Query Parameters:
        - q: Search query (required)
        - page: Page number (optional, default: 1)
        - page_size: Results per page (optional, default: 20, max: 100)
        - exact: Exact match only (optional, default: false)
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        # Get query parameters
        query = request.query_params.get('q', '').strip()
        page_number = request.query_params.get('page', 1)
        page_size = min(int(request.query_params.get('page_size', 20)), 100)
        exact_match = request.query_params.get('exact', 'false').lower() == 'true'
        
        if not query:
            return Response({
                'error': 'Search query is required',
                'detail': 'Provide a search query using the "q" parameter'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        if len(query) < 2:
            return Response({
                'error': 'Query too short',
                'detail': 'Search query must be at least 2 characters'
            }, status=status.HTTP_400_BAD_REQUEST)
        
        # Build search query
        if exact_match:
            # Exact match search
            users = User.objects.filter(
                Q(username__iexact=query) | Q(display_name__iexact=query)
            )
        else:
            # Partial match search (case-insensitive)
            users = User.objects.filter(
                Q(username__icontains=query) | Q(display_name__icontains=query)
            )
        
        # Exclude inactive users
        users = users.filter(is_active=True)
        
        # Order by relevance (exact matches first, then by username)
        users = users.order_by(
            '-verified',  # Verified users first
            'username'
        ).distinct()
        
        # Optimize query with select_related and prefetch_related
        users = users.select_related('profile')
        
        # Paginate results
        paginator = Paginator(users, page_size)
        page_obj = paginator.get_page(page_number)
        
        # Serialize data
        serializer = UserSearchSerializer(
            page_obj.object_list,
            many=True,
            context={'request': request}
        )
        
        return Response({
            'count': paginator.count,
            'total_pages': paginator.num_pages,
            'current_page': page_obj.number,
            'page_size': page_size,
            'next': page_obj.has_next(),
            'previous': page_obj.has_previous(),
            'results': serializer.data
        }, status=status.HTTP_200_OK)


class UserSearchSuggestionsView(APIView):
    """
    Get quick user search suggestions (autocomplete)
    Returns top 10 matches for fast autocomplete
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        query = request.query_params.get('q', '').strip()
        
        if not query or len(query) < 2:
            return Response({
                'suggestions': []
            }, status=status.HTTP_200_OK)
        
        # Get top 10 matches
        users = User.objects.filter(
            Q(username__istartswith=query) | Q(display_name__istartswith=query),
            is_active=True
        ).select_related('profile').order_by(
            '-verified',
            'username'
        ).distinct()[:10]
        
        serializer = UserSearchSerializer(
            users,
            many=True,
            context={'request': request}
        )
        
        return Response({
            'suggestions': serializer.data
        }, status=status.HTTP_200_OK)


class UserDetailView(APIView):
    """
    Get detailed information about a specific user
    """
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, username):
        try:
            user = User.objects.select_related('profile').get(
                username=username,
                is_active=True
            )
            
            serializer = UserSearchSerializer(
                user,
                context={'request': request}
            )
            
            return Response(serializer.data, status=status.HTTP_200_OK)
            
        except User.DoesNotExist:
            return Response({
                'error': 'User not found',
                'detail': f'No user found with username: {username}'
            }, status=status.HTTP_404_NOT_FOUND)