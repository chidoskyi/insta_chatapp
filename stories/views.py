from rest_framework import status, generics, permissions
from rest_framework.decorators import api_view, permission_classes
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.parsers import MultiPartParser, FormParser
from django.shortcuts import get_object_or_404
from django.contrib.auth import get_user_model
from django.utils import timezone
from django.db.models import Q, Max, Exists, OuterRef
from .models import Story, StoryView, StoryHighlight, HighlightStory, HighlightPost
from .serializers import (
    StorySerializer,
    StoryListSerializer,
    StoryViewerSerializer,
    UserStoriesSerializer,
    StoryHighlightSerializer,
    StoryHighlightListSerializer
)

User = get_user_model()


class StoryListCreateView(generics.ListCreateAPIView):
    """List active stories or create a new story"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return StorySerializer
        return StoryListSerializer
    
    def get_queryset(self):
        # Get active (non-expired) stories
        return Story.objects.filter(
            expires_at__gt=timezone.now()
        ).select_related('user')
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StoryDetailView(generics.RetrieveDestroyAPIView):
    """Retrieve or delete a story"""
    serializer_class = StorySerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        return Story.objects.filter(expires_at__gt=timezone.now())
    
    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Check if user can view this story
        if instance.user.is_private and instance.user != request.user:
            is_follower = instance.user.followers.filter(follower=request.user).exists()
            if not is_follower:
                return Response(
                    {'error': 'You must follow this user to view their stories'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Record view if not own story
        if instance.user != request.user:
            view, created = StoryView.objects.get_or_create(
                story=instance,
                viewer=request.user
            )
            if created:
                instance.increment_viewers()
        
        serializer = self.get_serializer(instance)
        return Response(serializer.data)
    
    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        
        # Only owner can delete
        if instance.user != request.user:
            return Response(
                {'error': 'You can only delete your own stories'},
                status=status.HTTP_403_FORBIDDEN
            )
        
        return super().destroy(request, *args, **kwargs)


class UserStoriesView(APIView):
    """Get all active stories for a specific user"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request, username):
        user = get_object_or_404(User, username=username)
        
        # Check privacy
        if user.is_private and user != request.user:
            is_follower = user.followers.filter(follower=request.user).exists()
            if not is_follower:
                return Response(
                    {'error': 'You must follow this user to view their stories'},
                    status=status.HTTP_403_FORBIDDEN
                )
        
        # Get active stories
        stories = Story.objects.filter(
            user=user,
            expires_at__gt=timezone.now()
        ).order_by('created_at')
        
        serializer = StoryListSerializer(stories, many=True, context={'request': request})
        return Response({
            'user': {
                'id': user.id,
                'username': user.username,
                'display_name': user.display_name,
                'avatar': user.avatar.url if user.avatar else None,
                'verified': user.verified
            },
            'stories': serializer.data
        })


class StoryViewersView(generics.ListAPIView):
    """Get list of users who viewed a story"""
    serializer_class = StoryViewerSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    def get_queryset(self):
        story_id = self.kwargs.get('story_id')
        story = get_object_or_404(Story, pk=story_id)
        
        # Only story owner can see viewers
        if story.user != self.request.user:
            return StoryView.objects.none()
        
        return StoryView.objects.filter(story=story).select_related('viewer')


class FeedStoriesView(APIView):
    """Get stories feed from followed users"""
    permission_classes = [permissions.IsAuthenticated]
    
    def get(self, request):
        user = request.user
        
        # Get users that current user follows + own user
        following_ids = list(user.following.values_list('followee_id', flat=True))
        following_ids.append(user.id)
        
        # Get active stories from followed users
        stories = Story.objects.filter(
            user_id__in=following_ids,
            expires_at__gt=timezone.now()
        ).select_related('user').order_by('user_id', 'created_at')
        
        # Group stories by user
        user_stories = {}
        for story in stories:
            user_id = story.user.id
            if user_id not in user_stories:
                user_stories[user_id] = {
                    'user': story.user,
                    'stories': [],
                    'has_unseen': False,
                    'latest_story_time': story.created_at
                }
            
            user_stories[user_id]['stories'].append(story)
            
            # Check if any story is unseen
            if not StoryView.objects.filter(story=story, viewer=user).exists():
                user_stories[user_id]['has_unseen'] = True
            
            # Update latest time
            if story.created_at > user_stories[user_id]['latest_story_time']:
                user_stories[user_id]['latest_story_time'] = story.created_at
        
        # Convert to list and sort (users with unseen stories first)
        result = []
        for user_data in user_stories.values():
            from accounts.serializers import UserMiniSerializer
            result.append({
                'user': UserMiniSerializer(user_data['user']).data,
                'stories': StoryListSerializer(
                    user_data['stories'],
                    many=True,
                    context={'request': request}
                ).data,
                'has_unseen': user_data['has_unseen'],
                'latest_story_time': user_data['latest_story_time']
            })
        
        # Sort: unseen first, then by latest story time
        result.sort(key=lambda x: (not x['has_unseen'], -x['latest_story_time'].timestamp()))
        
        return Response(result)


class StoryHighlightListCreateView(generics.ListCreateAPIView):
    """List highlights or create a new highlight"""
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_serializer_class(self):
        if self.request.method == 'POST':
            return StoryHighlightSerializer
        return StoryHighlightListSerializer
    
    def get_queryset(self):
        username = self.request.query_params.get('username')
        if username:
            user = get_object_or_404(User, username=username)
            return StoryHighlight.objects.filter(user=user)
        return StoryHighlight.objects.filter(user=self.request.user)
    
    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class StoryHighlightDetailView(generics.RetrieveUpdateDestroyAPIView):
    """Retrieve, update or delete a highlight"""
    serializer_class = StoryHighlightSerializer
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]
    
    def get_queryset(self):
        return StoryHighlight.objects.filter(user=self.request.user)
    
    def update(self, request, *args, **kwargs):
        instance = self.get_object()
        if instance.user != request.user:
            return Response(
                {'error': 'You can only update your own highlights'},
                status=status.HTTP_403_FORBIDDEN
            )
        return super().update(request, *args, **kwargs)


class AddStoryToHighlightView(APIView):
    """Add a story to a highlight"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, highlight_id, story_id):
        highlight = get_object_or_404(StoryHighlight, pk=highlight_id, user=request.user)
        story = get_object_or_404(Story, pk=story_id, user=request.user)
        
        # Check if already in highlight
        if HighlightStory.objects.filter(highlight=highlight, story=story).exists():
            return Response(
                {'error': 'Story already in highlight'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get next order
        from django.db.models import Max
        max_order = highlight.stories.aggregate(Max('order'))['order__max'] or -1
        max_post_order = highlight.posts.aggregate(Max('order'))['order__max'] or -1
        next_order = max(max_order, max_post_order) + 1
        
        HighlightStory.objects.create(
            highlight=highlight,
            story=story,
            order=next_order
        )
        
        return Response({'message': 'Story added to highlight'}, status=status.HTTP_201_CREATED)


class RemoveStoryFromHighlightView(APIView):
    """Remove a story from a highlight"""
    permission_classes = [permissions.IsAuthenticated]
    
    def delete(self, request, highlight_id, story_id):
        highlight = get_object_or_404(StoryHighlight, pk=highlight_id, user=request.user)
        
        highlight_story = get_object_or_404(
            HighlightStory,
            highlight=highlight,
            story_id=story_id
        )
        
        highlight_story.delete()
        
        return Response({'message': 'Story removed from highlight'})


class AddPostToHighlightView(APIView):
    """Add a post to a highlight"""
    permission_classes = [permissions.IsAuthenticated]
    
    def post(self, request, highlight_id, post_id):
        from posts.models import Post
        
        highlight = get_object_or_404(StoryHighlight, pk=highlight_id, user=request.user)
        post = get_object_or_404(Post, pk=post_id, user=request.user)
        
        # Check if already in highlight
        if HighlightPost.objects.filter(highlight=highlight, post=post).exists():
            return Response(
                {'error': 'Post already in highlight'},
                status=status.HTTP_400_BAD_REQUEST
            )
        
        # Get next order
        from django.db.models import Max
        max_order = highlight.stories.aggregate(Max('order'))['order__max'] or -1
        max_post_order = highlight.posts.aggregate(Max('order'))['order__max'] or -1
        next_order = max(max_order, max_post_order) + 1
        
        HighlightPost.objects.create(
            highlight=highlight,
            post=post,
            order=next_order
        )
        
        return Response({'message': 'Post added to highlight'}, status=status.HTTP_201_CREATED)


class RemovePostFromHighlightView(APIView):
    """Remove a post from a highlight"""
    permission_classes = [permissions.IsAuthenticated]
    
    def delete(self, request, highlight_id, post_id):
        highlight = get_object_or_404(StoryHighlight, pk=highlight_id, user=request.user)
        
        highlight_post = get_object_or_404(
            HighlightPost,
            highlight=highlight,
            post_id=post_id
        )
        
        highlight_post.delete()
        
        return Response({'message': 'Post removed from highlight'})


@api_view(['DELETE'])
@permission_classes([permissions.IsAuthenticated])
def delete_expired_stories(request):
    """Manual cleanup of expired stories (for testing, normally done via Celery)"""
    if not request.user.is_staff:
        return Response({'error': 'Admin only'}, status=status.HTTP_403_FORBIDDEN)
    
    expired_stories = Story.objects.filter(expires_at__lte=timezone.now())
    count = expired_stories.count()
    expired_stories.delete()
    
    return Response({'message': f'Deleted {count} expired stories'})