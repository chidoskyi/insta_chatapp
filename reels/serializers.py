from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Reel, ReelLike, ReelComment, ReelCommentLike, SavedReel, ReelView
import re

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user info for nested serialization"""
    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'avatar', 'verified']
        
    def to_representation(self, instance):
        data = super().to_representation(instance)
        # Get avatar from profile
        if hasattr(instance, 'profile') and instance.profile.avatar:
            data['avatar'] = instance.profile.avatar.url
        return data


class ReelCommentSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    replies_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ReelComment
        fields = [
            'id', 'reel', 'user', 'parent', 'body', 'likes_count',
            'is_liked', 'replies_count', 'created_at', 'updated_at', 'is_edited'
        ]
        read_only_fields = ['id', 'user', 'reel', 'likes_count', 'created_at', 'updated_at', 'is_edited']
    
    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return ReelCommentLike.objects.filter(comment=obj, user=request.user).exists()
        return False
    
    def get_replies_count(self, obj):
        return obj.replies.count()
    
    def validate_parent(self, value):
        if value and value.parent is not None:
            raise serializers.ValidationError("Cannot reply to a reply. Only one level of nesting allowed.")
        return value
    
    def validate(self, attrs):
        parent = attrs.get('parent')
        if parent:
            reel = self.context.get('reel')
            if reel and parent.reel != reel:
                raise serializers.ValidationError({"parent": "Parent comment must belong to the same reel"})
        return attrs


class ReelSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    tags = serializers.SerializerMethodField()
    video_file = serializers.FileField(write_only=True, required=False)
    
    class Meta:
        model = Reel
        fields = [
            'id', 'user', 'video', 'thumbnail', 'width', 'height', 'duration',
            'caption', 'audio_name', 'audio_url',
            'likes_count', 'comments_count', 'views_count', 'shares_count',
            'is_liked', 'is_saved', 'tags',
            'created_at', 'updated_at', 'is_edited',
            'video_file'  # write only
        ]
        read_only_fields = [
            'id', 'user', 'video', 'thumbnail', 'width', 'height', 'duration',
            'likes_count', 'comments_count', 'views_count', 'shares_count',
            'created_at', 'updated_at', 'is_edited'
        ]
    
    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return ReelLike.objects.filter(reel=obj, user=request.user).exists()
        return False
    
    def get_is_saved(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return SavedReel.objects.filter(reel=obj, user=request.user).exists()
        return False
    
    def get_tags(self, obj):
        from posts.serializers import TagSerializer
        from posts.models import Tag
        tags = Tag.objects.filter(tagged_reels__reel=obj)
        return TagSerializer(tags, many=True).data
    
    def extract_hashtags(self, caption):
        """Extract hashtags from caption"""
        if not caption:
            return []
        hashtag_pattern = r'#(\w+)'
        return list(set(re.findall(hashtag_pattern, caption.lower())))
    
    def create(self, validated_data):
        video_file = validated_data.pop('video_file', None)
        caption = validated_data.get('caption', '')
        
        if video_file:
            validated_data['video'] = video_file
        
        # Create reel
        reel = Reel.objects.create(**validated_data)
        
        # Extract and create tags
        from posts.models import Tag
        from .models import ReelTag
        
        hashtags = self.extract_hashtags(caption)
        for tag_name in hashtags:
            tag, created = Tag.objects.get_or_create(name=tag_name)
            if not created:
                tag.usage_count += 1
                tag.save()
            ReelTag.objects.create(reel=reel, tag=tag)
        
        return reel
    
    def update(self, instance, validated_data):
        validated_data.pop('video_file', None)  # Can't update video
        
        # If caption is updated, mark as edited and update tags
        if 'caption' in validated_data:
            old_caption = instance.caption
            new_caption = validated_data['caption']
            
            if old_caption != new_caption:
                instance.is_edited = True
                
                # Update tags
                from posts.models import Tag
                from .models import ReelTag
                
                old_tags = self.extract_hashtags(old_caption)
                new_tags = self.extract_hashtags(new_caption)
                
                # Remove old tags
                for tag_name in set(old_tags) - set(new_tags):
                    try:
                        tag = Tag.objects.get(name=tag_name)
                        ReelTag.objects.filter(reel=instance, tag=tag).delete()
                        tag.usage_count -= 1
                        if tag.usage_count <= 0:
                            tag.delete()
                        else:
                            tag.save()
                    except Tag.DoesNotExist:
                        pass
                
                # Add new tags
                for tag_name in set(new_tags) - set(old_tags):
                    tag, created = Tag.objects.get_or_create(name=tag_name)
                    if not created:
                        tag.usage_count += 1
                        tag.save()
                    ReelTag.objects.get_or_create(reel=instance, tag=tag)
        
        return super().update(instance, validated_data)


class ReelListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for reel feed"""
    user = UserMiniSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    
    class Meta:
        model = Reel
        fields = [
            'id', 'user', 'video', 'thumbnail', 'caption',
            'likes_count', 'comments_count', 'views_count',
            'is_liked', 'duration', 'audio_name', 'created_at'
        ]
    
    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return ReelLike.objects.filter(reel=obj, user=request.user).exists()
        return False