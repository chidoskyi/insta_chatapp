from rest_framework import status, generics, permissions, filters
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.contrib.contenttypes.models import ContentType

from posts.pagination import CustomCursorPagination
from .models import Mention, Post, Like, Comment, SavedPost, Tag
from .serializers import (
    MentionSerializer,
    PostSerializer,
    PostListSerializer,
    CommentSerializer,
    TagSerializer,
    UserMentionSerializer
)
from .permissions import IsOwnerOrReadOnly

User = get_user_model()


class PostListCreateView(generics.ListCreateAPIView):
    """List all posts or create a new post"""
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]  # Added JSONParser!
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return PostSerializer
        return PostListSerializer
    
    def get_queryset(self):
        queryset = Post.objects.select_related('user').prefetch_related('media')
        
        # Filter by visibility
        if self.request.user.is_authenticated:
            queryset = queryset.filter(
                Q(visibility='public') |
                Q(visibility='followers', user__followers__follower=self.request.user) |
                Q(user=self.request.user)
            ).distinct()
        else:
            queryset = queryset.filter(visibility='public')
        
        return queryset
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class PostDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a post"""
    queryset = Post.objects.all()
    serializer_class = PostSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    parser_classes = [MultiPartParser, FormParser, JSONParser]  # Added JSONParser!
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Check visibility permissions
        if instance.visibility == 'followers':
            if not request.user.is_authenticated:
                return Response(
                    {'error': 'This post is only visible to followers'},
                    status=status.HTTP_403_FORBIDDEN
                )
            if instance.user != request.user:
                is_follower = instance.user.followers.filter(follower=request.user).exists()
                if not is_follower:
                    return Response(
                        {'error': 'This post is only visible to followers'},
                        status=status.HTTP_403_FORBIDDEN
                    )
        elif instance.visibility == 'private':
            if not request.user.is_authenticated or instance.user != request.user:
                return Response(
                    {'error': 'This post is private'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Increment view count (can be optimized with Redis)
        instance.views_count += 1
        instance.save(update_fields=['views_count'])
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)


class UserPostsView(generics.ListAPIView):
    """List posts by a specific user"""
    serializer_class = PostListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        username = self.kwargs.get('username')
        user = get_object_or_404(User, username=username)
        
        queryset = Post.objects.filter(user=user).select_related('user').prefetch_related('media')
        
        # Check if requesting user can see posts
        if self.request.user.is_authenticated and self.request.user == user:
            return queryset  # User can see all their own posts
        
        # Check if profile is private
        if user.is_private:
            if not self.request.user.is_authenticated:
                return Post.objects.none()
            is_follower = user.followers.filter(follower=self.request.user).exists()
            if not is_follower:
                return Post.objects.none()
        
        # Filter by visibility
        if self.request.user.is_authenticated:
            queryset = queryset.filter(
                Q(visibility='public') |
                Q(visibility='followers', user__followers__follower=self.request.user)
            ).distinct()
        else:
            queryset = queryset.filter(visibility='public')
        
        return queryset


class FeedView(generics.ListAPIView):
    """Get personalized feed of posts from followed users"""
    serializer_class = PostListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomCursorPagination
    
    def get_queryset(self):
        user = self.request.user
        
        # Get posts from users that the current user follows
        following_ids = user.following.values_list('followee_id', flat=True)
        
        queryset = Post.objects.filter(
            Q(user_id__in=following_ids) | Q(user=user)
        ).select_related('user').prefetch_related('media')
        
        # Apply visibility filters
        queryset = queryset.filter(
            Q(visibility='public') |
            Q(visibility='followers') |
            Q(user=user)
        ).distinct()
        
        return queryset


class LikeToggleView(APIView):
    """Like or unlike a post"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, pk):
        post = get_object_or_404(Post, pk=pk)
        
        like, created = Like.objects.get_or_create(
            user=request.user,
            target_type='post',
            target_id=post.id
        )
        
        if not created:
            like.delete()
            post.decrement_likes()
            return Response({
                'message': 'Post unliked',
                'liked': False,
                'likes_count': post.likes_count
            })
        
        post.increment_likes()
        return Response({
            'message': 'Post liked',
            'liked': True,
            'likes_count': post.likes_count
        }, status=status.HTTP_201_CREATED)


class CommentListCreateView(generics.ListCreateAPIView):
    """List comments for a post or create a new comment"""
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = CustomCursorPagination
    
    
    def get_queryset(self):
        post_id = self.kwargs.get('post_id')
        # Only get top-level comments (no parent)
        return Comment.objects.filter(
            post_id=post_id,
            parent__isnull=True
        ).select_related('user').prefetch_related('replies')
    
    def get_serializer_context(self):
        """Add post to serializer context"""
        context = super().get_serializer_context()
        post_id = self.kwargs.get('post_id')
        try:
            context['post'] = Post.objects.get(pk=post_id)
        except Post.DoesNotExist:
            pass
        return context
    
    def create(self, request, *args, **kwargs):
        post_id = self.kwargs.get('post_id')
        post = get_object_or_404(Post, pk=post_id)
        
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        
        # Create comment with post and user
        comment = serializer.save(user=request.user, post=post)
        
        # Increment post comment count
        post.increment_comments()
        
        # Return created comment with full data
        response_serializer = CommentSerializer(comment, context={'request': request})
        return Response(response_serializer.data, status=status.HTTP_201_CREATED)


class CommentDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a comment"""
    queryset = Comment.objects.all()
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly, IsOwnerOrReadOnly]
    
    def perform_destroy(self, instance):
        post = instance.post
        instance.delete()
        post.decrement_comments()


class CommentRepliesView(generics.ListAPIView):
    """List replies to a comment"""
    serializer_class = CommentSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        comment_id = self.kwargs.get('comment_id')
        return Comment.objects.filter(parent_id=comment_id).select_related('user')


class CommentLikeToggleView(APIView):
    """Like or unlike a comment"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, pk):
        comment = get_object_or_404(Comment, pk=pk)
        
        like, created = Like.objects.get_or_create(
            user=request.user,
            target_type='comment',
            target_id=comment.id
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


class SavePostToggleView(APIView):
    """Save or unsave a post"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, pk):
        post = get_object_or_404(Post, pk=pk)
        folder = request.data.get('folder', '')
        
        saved, created = SavedPost.objects.get_or_create(
            user=request.user,
            post=post,
            defaults={'folder': folder}
        )
        
        if not created:
            saved.delete()
            return Response({
                'message': 'Post unsaved',
                'saved': False
            })
        
        return Response({
            'message': 'Post saved',
            'saved': True
        }, status=status.HTTP_201_CREATED)


class SavedPostsView(generics.ListAPIView):
    """List saved posts for current user"""
    serializer_class = PostListSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomCursorPagination
    
    def get_queryset(self):
        folder = self.request.query_params.get('folder', None)
        saved_posts = SavedPost.objects.filter(user=self.request.user)
        
        if folder:
            saved_posts = saved_posts.filter(folder=folder)
        
        post_ids = saved_posts.values_list('post_id', flat=True)
        return Post.objects.filter(id__in=post_ids).select_related('user').prefetch_related('media')


class TagPostsView(generics.ListAPIView):
    """List posts with a specific tag"""
    serializer_class = PostListSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    pagination_class = CustomCursorPagination
    
    def get_queryset(self):
        tag_name = self.kwargs.get('tag_name').lower()
        tag = get_object_or_404(Tag, name=tag_name)
        
        post_ids = tag.tagged_posts.values_list('post_id', flat=True)
        queryset = Post.objects.filter(id__in=post_ids).select_related('user').prefetch_related('media')
        
        # Apply visibility filters
        if self.request.user.is_authenticated:
            queryset = queryset.filter(
                Q(visibility='public') |
                Q(visibility='followers', user__followers__follower=self.request.user) |
                Q(user=self.request.user)
            ).distinct()
        else:
            queryset = queryset.filter(visibility='public')
        
        return queryset


class TrendingTagsView(generics.ListAPIView):
    """List trending tags"""
    serializer_class = TagSerializer
    permission_classes = [permissions.AllowAny]
    pagination_class = None
    queryset = Tag.objects.all().order_by('-usage_count')[:20]


class UserMentionsView(generics.ListAPIView):
    """Get all mentions for the authenticated user"""
    serializer_class = MentionSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CustomCursorPagination
    
    def get_queryset(self):
        user = self.request.user
        queryset = Mention.objects.filter(
            mentioned_user=user
        ).select_related(
            'mentioned_by',
            'content_type'
        ).prefetch_related('content_object')
        
        mention_type = self.request.query_params.get('type')
        if mention_type == 'post':
            post_type = ContentType.objects.get_for_model(Post)
            queryset = queryset.filter(content_type=post_type)
        elif mention_type == 'comment':
            comment_type = ContentType.objects.get_for_model(Comment)
            queryset = queryset.filter(content_type=comment_type)
        
        return queryset
class PostMentionsView(generics.ListAPIView):
    """Get all mentions in a specific post"""
    serializer_class = MentionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        post_id = self.kwargs.get('post_id')
        post_type = ContentType.objects.get_for_model(Post)
        return Mention.objects.filter(
            content_type=post_type,
            object_id=post_id
        ).select_related('mentioned_user', 'mentioned_by')


class CommentMentionsView(generics.ListAPIView):
    """Get all mentions in a specific comment"""
    serializer_class = MentionSerializer
    permission_classes = [permissions.IsAuthenticatedOrReadOnly]
    
    def get_queryset(self):
        comment_id = self.kwargs.get('comment_id')
        comment_type = ContentType.objects.get_for_model(Comment)
        return Mention.objects.filter(
            content_type=comment_type,
            object_id=comment_id
        ).select_related('mentioned_user', 'mentioned_by')

@api_view(['GET'])
@permission_classes([permissions.IsAuthenticated])
def search_users_for_mention(request):
    """
    Search users for mentions (autocomplete)
    Usage: /api/mentions/search/?q=john
    """
    query = request.GET.get('q', '').strip()
    
    if len(query) < 2:
        return Response({
            'results': [],
            'message': 'Query must be at least 2 characters'
        })
    
    users = User.objects.filter(
        Q(username__icontains=query) |
        Q(full_name__icontains=query)
    ).exclude(id=request.user.id)[:10]
    
    serializer = UserMentionSerializer(users, many=True)
    
    return Response({
        'results': serializer.data,
        'count': users.count()
    })

    