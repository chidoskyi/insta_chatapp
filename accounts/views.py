from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.views import TokenObtainPairView
from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from drf_spectacular.utils import extend_schema
from .serializers import (
    CustomTokenObtainPairSerializer,
    FollowToggleSerializer,
    UserRegistrationSerializer,
    UserSerializer,
    UserProfileSerializer,
    UserUpdateSerializer
)
from .models import Follow

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    """Register a new user"""
    queryset = User.objects.all()
    permission_classes = [permissions.AllowAny]
    serializer_class = UserRegistrationSerializer
    
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        
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


@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def current_user(request):
    """Get current authenticated user"""
    serializer = UserProfileSerializer(request.user, context={'request': request})
    return Response(serializer.data)