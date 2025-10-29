from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Q
from .models import Reel, ReelLike, ReelComment, ReelCommentLike, SavedReel, ReelView
from .serializers import ReelSerializer, ReelListSerializer, ReelCommentSerializer
from posts.permissions import IsOwnerOrReadOnly

User = get_user_model()


class ReelListCreateView(generics.ListCreateAPIView):
    """List reels feed or create a new reel"""
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return ReelSerializer
        return ReelListSerializer
    
    def get_queryset(self):
        # Exclude deleted reels
        queryset = Reel.objects.filter(is_deleted=False).select_related('user')
        
        # Order by recent or trending
        order_by = self.request.query_params.get('order_by', 'recent')
        
        if order_by == 'trending':
            # Trending: high views and likes in last 7 days
            from django.utils import timezone
            from datetime import timedelta
            week_ago = timezone.now() - timedelta(days=7)
            queryset = queryset.filter(created_at__gte=week_ago).order_by('-views_count', '-likes_count')
        else:
            # Recent: newest first
            queryset = queryset.order_by('-created_at')
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class ReelDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a reel"""
    queryset = Reel.objects.filter(is_deleted=False)
    serializer_class = ReelSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    parser_classes = [MultiPartParser, FormParser]
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Increment view count
        instance.increment_views()
        
        # Track detailed view
        if request.user.is_authenticated:
            ReelView.objects.get_or_create(
                reel=instance,
                user=request.user,
                defaults={'watch_time': 0, 'completed': False}
            )
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Soft delete
        instance.is_deleted = True
        instance.save()
        
        return Response({'message': 'Reel deleted'})


class UserReelsView(generics.ListAPIView):
    """List reels by a specific user"""
    serializer_class = ReelListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        username = self.kwargs.get('username')
        user = get_object_or_404(User, username=username)
        
        queryset = Reel.objects.filter(
            user=user,
            is_deleted=False
        ).select_related('user')
        
        return queryset.order_by('-created_at')


class ReelFeedView(generics.ListAPIView):
    """Get personalized reel feed from followed users"""
    serializer_class = ReelListSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        user = self.request.user
        
        # Get reels from users that the current user follows
        following_ids = user.following.values_list('followee_id', flat=True)
        
        queryset = Reel.objects.filter(
            Q(user_id__in=following_ids) | Q(user=user),
            is_deleted=False
        ).select_related('user')
        
        return queryset.order_by('-created_at')


class ReelLikeToggleView(APIView):
    """Like or unlike a reel"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, pk):
        reel = get_object_or_404(Reel, pk=pk, is_deleted=False)
        
        like, created = ReelLike.objects.get_or_create(
            reel=reel,
            user=request.user
        )
        
        if not created:
            like.delete()
            reel.decrement_likes()
            return Response({
                'message': 'Reel unliked',
                'liked': False,
                'likes_count': reel.likes_count
            })
        
        reel.increment_likes()
        return Response({
            'message': 'Reel liked',
            'liked': True,
            'likes_count': reel.likes_count
        }, status=status.HTTP_201_CREATED)


class ReelCommentListCreateView(generics.ListCreateAPIView):
    """List comments for a reel or create a new comment"""
    serializer_class = ReelCommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        reel_id = self.kwargs.get('reel_id')
        # Only get top-level comments
        return ReelComment.objects.filter(
            reel_id=reel_id,
            parent__isnull=True
        ).select_related('user').prefetch_related('replies')
    
    def get_serializer_context(self):
        context = super().get_serializer_context()
        reel_id = self.kwargs.get('reel_id')
        try:
            context['reel'] = Reel.objects.get(pk=reel_id)
        except Reel.DoesNotExist:
            pass
        return context
    
    def create(self, request, *args, **kwargs):
        reel_id = self.kwargs.get('reel_id')
        reel = get_object_or_404(Reel, pk=reel_id, is_deleted=False)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        comment = serializer.save(user=request.user, reel=reel)
        reel.increment_comments()
        
        response_serializer = ReelCommentSerializer(comment, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class ReelCommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a comment"""
    queryset = ReelComment.objects.all()
    serializer_class = ReelCommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    
    def perform_destroy(self, instance):
        reel = instance.reel
        instance.delete()
        reel.decrement_comments()


class ReelCommentLikeToggleView(APIView):
    """Like or unlike a reel comment"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, pk):
        comment = get_object_or_404(ReelComment, pk=pk)
        
        like, created = ReelCommentLike.objects.get_or_create(
            comment=comment,
            user=request.user
        )
        
        if not created:
            like.delete()
            comment.decrement_likes()
            return Response({
                'message': 'Comment unliked',
                'liked': False,
                'likes_count': comment.likes_count
            })
        
        comment.increment_likes()
        return Response({
            'message': 'Comment liked',
            'liked': True,
            'likes_count': comment.likes_count
        }, status=status.HTTP_201_CREATED)


class SaveReelToggleView(APIView):
    """Save or unsave a reel"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, pk):
        reel = get_object_or_404(Reel, pk=pk, is_deleted=False)
        folder = request.data.get('folder', '')
        
        saved, created = SavedReel.objects.get_or_create(
            user=request.user,
            reel=reel,
            defaults={'folder': folder}
        )
        
        if not created:
            saved.delete()
            return Response({
                'message': 'Reel unsaved',
                'saved': False
            })
        
        return Response({
            'message': 'Reel saved',
            'saved': True
        }, status=status.HTTP_201_CREATED)


class SavedReelsView(generics.ListAPIView):
    """List saved reels for current user"""
    serializer_class = ReelListSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        folder = self.request.query_params.get('folder', None)
        saved_reels = SavedReel.objects.filter(user=self.request.user)
        
        if folder:
            saved_reels = saved_reels.filter(folder=folder)
        
        reel_ids = saved_reels.values_list('reel_id', flat=True)
        return Reel.objects.filter(id__in=reel_ids, is_deleted=False).select_related('user')


class ReelShareView(APIView):
    """Track reel shares"""
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def post(self, request, pk):
        reel = get_object_or_404(Reel, pk=pk, is_deleted=False)
        
        # Increment share count
        reel.increment_shares()
        
        return Response({
            'message': 'Share tracked',
            'shares_count': reel.shares_count
        })


class TrendingReelsView(generics.ListAPIView):
    """Get trending reels based on views and engagement"""
    serializer_class = ReelListSerializer
    permission_classes = [permissions.AllowAny]
    
    def get_queryset(self):
        from django.utils import timezone
        from datetime import timedelta
        
        # Trending in last 7 days
        week_ago = timezone.now() - timedelta(days=7)
        
        return Reel.objects.filter(
            created_at__gte=week_ago,
            is_deleted=False
        ).select_related('user').order_by('-views_count', '-likes_count')[:50]


@api_view(['POST'])
@permission_classes([permissions.IsAuthenticatedOrReadOnly])
def track_reel_view(request, pk):
    """Track detailed reel view with watch time"""
    reel = get_object_or_404(Reel, pk=pk, is_deleted=False)
    
    watch_time = request.data.get('watch_time', 0)
    completed = request.data.get('completed', False)
    
    if request.user.is_authenticated:
        view, created = ReelView.objects.get_or_create(
            reel=reel,
            user=request.user
        )
        view.watch_time = watch_time
        view.completed = completed
        view.save()
    else:
        # Track anonymous views with session
        session_key = request.session.session_key
        if not session_key:
            request.session.create()
            session_key = request.session.session_key
        
        view, created = ReelView.objects.get_or_create(
            reel=reel,
            session_key=session_key
        )
        view.watch_time = watch_time
        view.completed = completed
        view.save()
    
    return Response({'message': 'View tracked'})