from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from .models import (
    PrivacySettings,
    BlockedUser,
    MutedUser,
    RestrictedUser,
    ActivityLog,
    CloseFriendsList
)
from .serializers import (
    PrivacySettingsSerializer,
    BlockedUserSerializer,
    MutedUserSerializer,
    RestrictedUserSerializer,
    ActivityLogSerializer,
    CloseFriendsSerializer
)

User = get_user_model()


class PrivacySettingsView(APIView):
    """Get or update privacy settings"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        settings, created = PrivacySettings.objects.get_or_create(user=request.user)
        serializer = PrivacySettingsSerializer(settings)
        return Response(serializer.data)
    
    def put(self, request):
        settings, created = PrivacySettings.objects.get_or_create(user=request.user)
        serializer = PrivacySettingsSerializer(
            settings,
            data=request.data,
            partial=True
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        
        # Log activity
        log_activity(request.user, 'settings_change', request)
        
        return Response(serializer.data)
    
    patch = put


class BlockedUsersListView(generics.ListAPIView):
    """List blocked users"""
    serializer_class = BlockedUserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return BlockedUser.objects.filter(blocker=self.request.user).select_related('blocked')


class BlockUserView(APIView):
    """Block a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_block = get_object_or_404(User, username=username)
        
        if user_to_block == request.user:
            return Response(
                {'error': 'You cannot block yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Check if already blocked
        if BlockedUser.objects.filter(blocker=request.user, blocked=user_to_block).exists():
            return Response(
                {'error': 'User is already blocked'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Block user
        blocked = BlockedUser.objects.create(
            blocker=request.user,
            blocked=user_to_block,
            reason=request.data.get('reason', '')
        )
        
        # Unfollow each other
        from accounts.models import Follow
        Follow.objects.filter(follower=request.user, followee=user_to_block).delete()
        Follow.objects.filter(follower=user_to_block, followee=request.user).delete()
        
        # Remove from close friends
        CloseFriendsList.objects.filter(
            user=request.user,
            close_friend=user_to_block
        ).delete()
        
        serializer = BlockedUserSerializer(blocked)
        return Response(serializer.data, status=status.HTTP_201_CREATED)


class UnblockUserView(APIView):
    """Unblock a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_unblock = get_object_or_404(User, username=username)
        
        try:
            blocked = BlockedUser.objects.get(
                blocker=request.user,
                blocked=user_to_unblock
            )
            blocked.delete()
            return Response({'message': f'Unblocked {username}'})
        except BlockedUser.DoesNotExist:
            return Response(
                {'error': 'User is not blocked'},
                status=status.HTTP_400_BAD_REQUEST
            )


class MutedUsersListView(generics.ListAPIView):
    """List muted users"""
    serializer_class = MutedUserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return MutedUser.objects.filter(muter=self.request.user).select_related('muted')


class MuteUserView(APIView):
    """Mute a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_mute = get_object_or_404(User, username=username)
        
        if user_to_mute == request.user:
            return Response(
                {'error': 'You cannot mute yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        muted, created = MutedUser.objects.get_or_create(
            muter=request.user,
            muted=user_to_mute,
            defaults={
                'mute_posts': request.data.get('mute_posts', True),
                'mute_stories': request.data.get('mute_stories', True),
                'mute_reels': request.data.get('mute_reels', True),
            }
        )
        
        if not created:
            # Update existing mute settings
            muted.mute_posts = request.data.get('mute_posts', muted.mute_posts)
            muted.mute_stories = request.data.get('mute_stories', muted.mute_stories)
            muted.mute_reels = request.data.get('mute_reels', muted.mute_reels)
            muted.save()
        
        serializer = MutedUserSerializer(muted)
        return Response(serializer.data, status=status.HTTP_201_CREATED if created else status.HTTP_200_OK)


class UnmuteUserView(APIView):
    """Unmute a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_unmute = get_object_or_404(User, username=username)
        
        try:
            muted = MutedUser.objects.get(
                muter=request.user,
                muted=user_to_unmute
            )
            muted.delete()
            return Response({'message': f'Unmuted {username}'})
        except MutedUser.DoesNotExist:
            return Response(
                {'error': 'User is not muted'},
                status=status.HTTP_400_BAD_REQUEST
            )


class RestrictedUsersListView(generics.ListAPIView):
    """List restricted users"""
    serializer_class = RestrictedUserSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return RestrictedUser.objects.filter(restrictor=self.request.user).select_related('restricted')


class RestrictUserView(APIView):
    """Restrict a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_restrict = get_object_or_404(User, username=username)
        
        if user_to_restrict == request.user:
            return Response(
                {'error': 'You cannot restrict yourself'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        restricted, created = RestrictedUser.objects.get_or_create(
            restrictor=request.user,
            restricted=user_to_restrict
        )
        
        serializer = RestrictedUserSerializer(restricted)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class UnrestrictUserView(APIView):
    """Unrestrict a user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_unrestrict = get_object_or_404(User, username=username)
        
        try:
            restricted = RestrictedUser.objects.get(
                restrictor=request.user,
                restricted=user_to_unrestrict
            )
            restricted.delete()
            return Response({'message': f'Unrestricted {username}'})
        except RestrictedUser.DoesNotExist:
            return Response(
                {'error': 'User is not restricted'},
                status=status.HTTP_400_BAD_REQUEST
            )


class ActivityLogView(generics.ListAPIView):
    """View activity log"""
    serializer_class = ActivityLogSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return ActivityLog.objects.filter(user=self.request.user)


class CloseFriendsListView(generics.ListAPIView):
    """List close friends"""
    serializer_class = CloseFriendsSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return CloseFriendsList.objects.filter(user=self.request.user).select_related('close_friend')


class AddCloseFriendView(APIView):
    """Add user to close friends"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_add = get_object_or_404(User, username=username)
        
        if user_to_add == request.user:
            return Response(
                {'error': 'You cannot add yourself to close friends'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        close_friend, created = CloseFriendsList.objects.get_or_create(
            user=request.user,
            close_friend=user_to_add
        )
        
        serializer = CloseFriendsSerializer(close_friend)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED if created else status.HTTP_200_OK
        )


class RemoveCloseFriendView(APIView):
    """Remove user from close friends"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, username):
        user_to_remove = get_object_or_404(User, username=username)
        
        try:
            close_friend = CloseFriendsList.objects.get(
                user=request.user,
                close_friend=user_to_remove
            )
            close_friend.delete()
            return Response({'message': f'Removed {username} from close friends'})
        except CloseFriendsList.DoesNotExist:
            return Response(
                {'error': 'User is not in close friends'},
                status=status.HTTP_400_BAD_REQUEST
            )


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_account(request):
    """Delete user account (soft delete)"""
    password = request.data.get('password')
    
    if not password:
        return Response(
            {'error': 'Password is required'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    if not request.user.check_password(password):
        return Response(
            {'error': 'Incorrect password'},
            status=status.HTTP_400_BAD_REQUEST
        )
    
    # Log activity before deletion
    log_activity(request.user, 'account_deletion', request)
    
    # Soft delete: deactivate account
    request.user.is_active = False
    request.user.save()
    
    return Response({'message': 'Account deactivated successfully'})


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticated])
def download_data(request):
    """Request to download user data (GDPR)"""
    from .tasks import generate_user_data_export
    
    # Trigger async task
    generate_user_data_export.delay(request.user.id)
    
    return Response({
        'message': 'Your data export has been requested. You will receive an email when it\'s ready.'
    })


# Helper function
def log_activity(user, action_type, request):
    """Log user activity"""
    ip_address = get_client_ip(request)
    user_agent = request.META.get('HTTP_USER_AGENT', '')
    
    ActivityLog.objects.create(
        user=user,
        action_type=action_type,
        ip_address=ip_address,
        user_agent=user_agent
    )


def get_client_ip(request):
    """Get client IP address"""
    x_forwarded_for = request.META.get('HTTP_X_FORWARDED_FOR')
    if x_forwarded_for:
        ip = x_forwarded_for.split(',')[0]
    else:
        ip = request.META.get('REMOTE_ADDR')
    return ip