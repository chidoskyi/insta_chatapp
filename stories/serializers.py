from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import HighlightPost, Story, StoryView, StoryHighlight, HighlightStory

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user info for nested serialization"""
    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'avatar', 'verified']


class StoryViewerSerializer(serializers.ModelSerializer):
    """Serializer for story viewers"""
    viewer = UserMiniSerializer(read_only=True)
    
    class Meta:
        model = StoryView
        fields = ['id', 'viewer', 'viewed_at']
        read_only_fields = ['id', 'viewed_at']


class StorySerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    media_file = serializers.FileField(write_only=True, required=False)
    is_viewed = serializers.SerializerMethodField()
    time_remaining = serializers.ReadOnlyField()
    
    class Meta:
        model = Story
        fields = [
            'id', 'user', 'media_type', 'media', 'thumbnail',
            'width', 'height', 'duration', 'caption',
            'viewers_count', 'is_viewed', 'time_remaining',
            'created_at', 'expires_at',
            'media_file'  # write only
        ]
        read_only_fields = [
            'id', 'user', 'media', 'thumbnail', 'width', 'height',
            'duration', 'viewers_count', 'created_at', 'expires_at'
        ]
    
    def get_is_viewed(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return StoryView.objects.filter(
                story=obj,
                viewer=request.user
            ).exists()
        return False
    
    def create(self, validated_data):
        media_file = validated_data.pop('media_file', None)
        
        if media_file:
            # Determine media type
            if media_file.content_type.startswith('video'):
                validated_data['media_type'] = 'video'
            else:
                validated_data['media_type'] = 'image'
            
            validated_data['media'] = media_file
        
        return Story.objects.create(**validated_data)


class StoryListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for story lists"""
    user = UserMiniSerializer(read_only=True)
    is_viewed = serializers.SerializerMethodField()
    
    class Meta:
        model = Story
        fields = [
            'id', 'user', 'media_type', 'thumbnail', 'is_viewed',
            'created_at', 'time_remaining'
        ]
    
    def get_is_viewed(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return StoryView.objects.filter(
                story=obj,
                viewer=request.user
            ).exists()
        return False


class UserStoriesSerializer(serializers.Serializer):
    """Groups stories by user"""
    user = UserMiniSerializer(read_only=True)
    stories = StoryListSerializer(many=True, read_only=True)
    has_unseen = serializers.BooleanField(read_only=True)
    latest_story_time = serializers.DateTimeField(read_only=True)


class HighlightStorySerializer(serializers.ModelSerializer):
    """Story inside a highlight"""
    story = StorySerializer(read_only=True)
    
    class Meta:
        model = HighlightStory
        fields = ['id', 'story', 'order', 'added_at']
        read_only_fields = ['id', 'added_at']


class HighlightPostSerializer(serializers.ModelSerializer):
    """Post inside a highlight"""
    post = serializers.SerializerMethodField()
    
    class Meta:
        model = HighlightPost
        fields = ['id', 'post', 'order', 'added_at']
        read_only_fields = ['id', 'added_at']
    
    def get_post(self, obj):
        from posts.serializers import PostListSerializer
        return PostListSerializer(obj.post, context=self.context).data


class StoryHighlightSerializer(serializers.ModelSerializer):
    """Story highlight/collection with both stories and posts"""
    user = UserMiniSerializer(read_only=True)
    stories = HighlightStorySerializer(many=True, read_only=True)
    posts = HighlightPostSerializer(many=True, read_only=True)
    items_count = serializers.SerializerMethodField()
    story_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    post_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = StoryHighlight
        fields = [
            'id', 'user', 'title', 'cover_image',
            'stories', 'posts', 'items_count',
            'story_ids', 'post_ids',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'user', 'created_at', 'updated_at']
    
    def get_items_count(self, obj):
        return obj.stories.count() + obj.posts.count()
    
    def create(self, validated_data):
        story_ids = validated_data.pop('story_ids', [])
        post_ids = validated_data.pop('post_ids', [])
        highlight = StoryHighlight.objects.create(**validated_data)
        
        # Add stories to highlight
        for order, story_id in enumerate(story_ids):
            try:
                story = Story.objects.get(id=story_id, user=validated_data['user'])
                HighlightStory.objects.create(
                    highlight=highlight,
                    story=story,
                    order=order
                )
            except Story.DoesNotExist:
                pass
        
        # Add posts to highlight
        from posts.models import Post
        offset = len(story_ids)
        for order, post_id in enumerate(post_ids):
            try:
                post = Post.objects.get(id=post_id, user=validated_data['user'])
                HighlightPost.objects.create(
                    highlight=highlight,
                    post=post,
                    order=offset + order
                )
            except Post.DoesNotExist:
                pass
        
        return highlight
    
    def update(self, instance, validated_data):
        story_ids = validated_data.pop('story_ids', None)
        post_ids = validated_data.pop('post_ids', None)
        
        # Update basic fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update stories if provided
        if story_ids is not None:
            # Remove existing stories
            instance.stories.all().delete()
            
            # Add new stories
            for order, story_id in enumerate(story_ids):
                try:
                    story = Story.objects.get(id=story_id, user=instance.user)
                    HighlightStory.objects.create(
                        highlight=instance,
                        story=story,
                        order=order
                    )
                except Story.DoesNotExist:
                    pass
        
        # Update posts if provided
        if post_ids is not None:
            # Remove existing posts
            instance.posts.all().delete()
            
            # Add new posts
            from posts.models import Post
            offset = instance.stories.count() if story_ids is None else len(story_ids)
            for order, post_id in enumerate(post_ids):
                try:
                    post = Post.objects.get(id=post_id, user=instance.user)
                    HighlightPost.objects.create(
                        highlight=instance,
                        post=post,
                        order=offset + order
                    )
                except Post.DoesNotExist:
                    pass
        
        return instance


class StoryHighlightListSerializer(serializers.ModelSerializer):
    """Lightweight highlight list"""
    items_count = serializers.SerializerMethodField()
    
    class Meta:
        model = StoryHighlight
        fields = ['id', 'title', 'cover_image', 'items_count', 'created_at']
    
    def get_items_count(self, obj):
        return obj.stories.count() + obj.posts.count()