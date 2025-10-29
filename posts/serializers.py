from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Mention, Post, PostMedia, Like, Comment, Reaction, SavedPost, Tag, PostTag
from django.contrib.contenttypes.models import ContentType
import re

User = get_user_model()

class UserMentionSerializer(serializers.ModelSerializer):
    """Lightweight serializer for mentioned users"""
    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'avatar']
    
    def get_avatar(self, obj):
        """Get avatar from profile model"""
        if hasattr(obj, 'profile') and obj.profile.avatar:
            return obj.profile.avatar.url
        return None

class PostMediaSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostMedia
        fields = [
            'id', 'media_type', 'file', 'thumbnail', 
            'text_content', 'background_color', 'text_color',
            'width', 'height', 'duration', 'order'
        ]
        read_only_fields = ['id', 'thumbnail', 'width', 'height', 'duration']


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'name', 'usage_count']
        read_only_fields = ['id', 'usage_count']


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user info for nested serialization"""
    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'verified']


class CommentSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    is_liked = serializers.SerializerMethodField()
    replies_count = serializers.SerializerMethodField()
    tagged_users = serializers.SerializerMethodField()
    mentions = serializers.SerializerMethodField()
    replies = serializers.SerializerMethodField()
    user_reaction = serializers.SerializerMethodField()
    reactions_breakdown = serializers.SerializerMethodField()
    
    class Meta:
        model = Comment
        fields = [
            'id', 'post', 'user', 'parent', 'body', 
            'likes_count', 'reactions_count', 'tagged_users', 'mentions',
            'is_liked', 'user_reaction', 'reactions_breakdown', 'replies',
            'replies_count', 'created_at', 'updated_at', 'is_edited'
        ]
        read_only_fields = [
            'id', 'user', 'post', 'likes_count', 'reactions_count',
            'created_at', 'updated_at', 'is_edited'
        ]
    
    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return Like.objects.filter(
                user=request.user,
                target_type='comment',
                target_id=obj.id
            ).exists()
        return False
    
    def get_replies_count(self, obj):
        return obj.replies.count()
    
    def get_replies(self, obj):
        """Get nested replies for this comment"""
        if hasattr(obj, 'replies'):
            replies = obj.replies.all().select_related('user')
            return CommentSerializer(
                replies, 
                many=True, 
                context=self.context
            ).data
        return []
    
    def get_user_reaction(self, obj):
        """Get the current user's reaction if any"""
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            try:
                reaction = Reaction.objects.get(
                    user=request.user,
                    target_type='comment',
                    target_id=obj.id
                )
                return {
                    'reaction_type': reaction.reaction_type,
                    'emoji': dict(Reaction.REACTION_TYPES).get(reaction.reaction_type, '')
                }
            except Reaction.DoesNotExist:
                return None
        return None
    
    def get_reactions_breakdown(self, obj):
        """Get breakdown of all reactions on this comment"""
        return obj.get_reactions_breakdown()
    
    def get_mentions(self, obj):
        """Get all mentions in this comment"""
        content_type = ContentType.objects.get_for_model(Comment)
        mentions = Mention.objects.filter(
            content_type=content_type,
            object_id=obj.id
        ).select_related('mentioned_user', 'mentioned_by')
        return MentionSerializer(mentions, many=True).data
    
    def get_tagged_users(self, obj):
        """Get tagged users for this comment if applicable"""
        # Implement based on your tagging logic
        return []
    
    def validate_parent(self, value):
        if value and value.parent is not None:
            raise serializers.ValidationError(
                "Cannot reply to a reply. Only one level of nesting allowed."
            )
        return value
    
    def validate(self, attrs):
        # Ensure parent comment belongs to the same post
        parent = attrs.get('parent')
        if parent:
            # Get post from context (set in the view)
            post = self.context.get('post')
            if post and parent.post != post:
                raise serializers.ValidationError({
                    "parent": "Parent comment must belong to the same post"
                })
        return attrs
    
    def create(self, validated_data):
        content = validated_data.get('body', '')
        comment = super().create(validated_data)
        self._create_mentions(comment, content, validated_data['user'])
        return comment
    
    def update(self, instance, validated_data):
        content = validated_data.get('body')
        
        if content and content != instance.body:
            content_type = ContentType.objects.get_for_model(Comment)
            Mention.objects.filter(
                content_type=content_type,
                object_id=instance.id
            ).delete()
            self._create_mentions(instance, content, instance.user)
        
        return super().update(instance, validated_data)
    
    def _create_mentions(self, comment, content, mentioned_by):
        """Helper method to create mention objects from content"""
        mention_pattern = r'@(\w+)'
        usernames = re.findall(mention_pattern, content)
        
        if not usernames:
            return
        
        mentioned_users = User.objects.filter(username__in=usernames)
        content_type = ContentType.objects.get_for_model(Comment)
        
        mentions_to_create = []
        for user in mentioned_users:
            position = content.find(f'@{user.username}')
            mentions_to_create.append(
                Mention(
                    mentioned_user=user,
                    mentioned_by=mentioned_by,
                    content_type=content_type,
                    object_id=comment.id,
                    position=position
                )
            )
        
        if mentions_to_create:
            Mention.objects.bulk_create(mentions_to_create, ignore_conflicts=True)

class ReactionSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    emoji = serializers.SerializerMethodField()
    target_object = serializers.SerializerMethodField()
    
    class Meta:
        model = Reaction
        fields = [
            'id', 'user', 'target_type', 'target_id', 'reaction_type',
            'emoji', 'target_object', 'created_at'
        ]
        read_only_fields = ['id', 'user', 'created_at']
    
    def get_emoji(self, obj):
        """Get the emoji representation"""
        return dict(Reaction.REACTION_TYPES).get(obj.reaction_type, '')
    
    def get_target_object(self, obj):
        """Get the target object (post or comment)"""
        if obj.target_type == 'post':
            try:
                post = Post.objects.get(id=obj.target_id)
                return {
                    'type': 'post',
                    'id': post.id,
                    'caption': post.caption[:100] if post.caption else None
                }
            except Post.DoesNotExist:
                return None
        elif obj.target_type == 'comment':
            try:
                comment = Comment.objects.get(id=obj.target_id)
                return {
                    'type': 'comment',
                    'id': comment.id,
                    'body': comment.body[:100] if comment.body else None
                }
            except Comment.DoesNotExist:
                return None
        return None
    
    def validate_reaction_type(self, value):
        """Validate reaction type"""
        if value not in dict(Reaction.REACTION_TYPES):
            raise serializers.ValidationError("Invalid reaction type")
        return value
    
    def validate(self, attrs):
        """Validate the reaction data"""
        target_type = attrs.get('target_type')
        target_id = attrs.get('target_id')
        
        # Verify target exists
        if target_type == 'post':
            if not Post.objects.filter(id=target_id).exists():
                raise serializers.ValidationError({
                    "target_id": "Post not found"
                })
        elif target_type == 'comment':
            if not Comment.objects.filter(id=target_id).exists():
                raise serializers.ValidationError({
                    "target_id": "Comment not found"
                })
        
        return attrs





class PostSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    media = PostMediaSerializer(many=True, read_only=True)
    tags = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    is_saved = serializers.SerializerMethodField()
    tagged_users = serializers.SerializerMethodField()
    mentions = serializers.SerializerMethodField()
    
    # For creating posts with media files
    media_files = serializers.ListField(
        child=serializers.FileField(),
        write_only=True,
        required=False
    )
    
    # For creating text slides in carousel
    text_slides = serializers.ListField(
        child=serializers.DictField(),
        write_only=True,
        required=False,
        help_text="List of text slides with 'content', 'background_color', 'text_color', and 'order'"
    )
    
    class Meta:
        model = Post
        fields = [
            'id', 'user', 'type', 'caption', 'visibility', 'location',
            'likes_count', 'comments_count', 'views_count',
            'media', 'tags', 'is_liked', 'is_saved',
            'created_at', 'updated_at', 'is_edited',
            'media_files', 'text_slides', 'tagged_users', 'mentions'
        ]
        read_only_fields = [
            'id', 'user', 'likes_count', 'comments_count', 'views_count',
            'created_at', 'updated_at', 'is_edited'
        ]
    
    def get_tags(self, obj):
        tags = Tag.objects.filter(tagged_posts__post=obj)
        return TagSerializer(tags, many=True).data
    
    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return Like.objects.filter(
                user=request.user,
                target_type='post',
                target_id=obj.id
            ).exists()
        return False
    
    def get_is_saved(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return SavedPost.objects.filter(user=request.user, post=obj).exists()
        return False
    
    def extract_hashtags(self, caption):
        """Extract hashtags from caption"""
        if not caption:
            return []
        hashtag_pattern = r'#(\w+)'
        return list(set(re.findall(hashtag_pattern, caption.lower())))
    
    def validate_media_files(self, value):
        """Validate media files"""
        if len(value) > 10:
            raise serializers.ValidationError("Maximum 10 media files allowed per post")
        
        # Validate file types
        allowed_image_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        allowed_video_types = ['video/mp4', 'video/quicktime', 'video/x-msvideo', 'video/webm']
        
        for file in value:
            content_type = file.content_type
            if content_type not in allowed_image_types + allowed_video_types:
                raise serializers.ValidationError(
                    f"Unsupported file type: {content_type}. "
                    "Only images (JPEG, PNG, GIF, WebP) and videos (MP4, MOV, AVI, WebM) are allowed."
                )
            
            # Check file size (max 50MB for videos, 10MB for images)
            max_size = 50 * 1024 * 1024 if content_type in allowed_video_types else 10 * 1024 * 1024
            if file.size > max_size:
                max_size_mb = 50 if content_type in allowed_video_types else 10
                raise serializers.ValidationError(
                    f"File size exceeds {max_size_mb}MB limit"
                )
        
        return value
    
    def validate_text_slides(self, value):
        """Validate text slides"""
        if len(value) > 10:
            raise serializers.ValidationError("Maximum 10 text slides allowed per post")
        
        for slide in value:
            if 'content' not in slide:
                raise serializers.ValidationError("Each text slide must have 'content'")
            
            if len(slide['content']) > 500:
                raise serializers.ValidationError("Text slide content cannot exceed 500 characters")
            
            # Validate hex colors if provided
            if 'background_color' in slide:
                if not re.match(r'^#[0-9A-Fa-f]{6}$', slide['background_color']):
                    raise serializers.ValidationError("Invalid background_color format. Use hex format like #4A90E2")
            
            if 'text_color' in slide:
                if not re.match(r'^#[0-9A-Fa-f]{6}$', slide['text_color']):
                    raise serializers.ValidationError("Invalid text_color format. Use hex format like #ffffff")
        
        return value
    
    def validate(self, data):
        """Ensure at least caption, media files, or text slides are provided"""
        media_files = data.get('media_files', [])
        text_slides = data.get('text_slides', [])
        caption = data.get('caption', '')
        
        if not media_files and not text_slides and not caption:
            raise serializers.ValidationError(
                "Post must have at least a caption, media files, or text slides"
            )
        
        # Check total items in carousel
        total_items = len(media_files) + len(text_slides)
        if total_items > 10:
            raise serializers.ValidationError("Total carousel items (media + text slides) cannot exceed 10")
        
        return data
    
    def create(self, validated_data):
        from .tasks import generate_thumbnail, process_video_metadata, generate_text_slide_image
        
        media_files = validated_data.pop('media_files', [])
        text_slides = validated_data.pop('text_slides', [])
        caption = validated_data.get('caption', '')
        
        # Determine post type
        total_items = len(media_files) + len(text_slides)
        
        if total_items == 0:
            # Text-only post (just caption)
            validated_data['type'] = 'text'
        elif total_items == 1:
            # Single item post
            if len(media_files) == 1:
                file = media_files[0]
                if file.content_type.startswith('video'):
                    validated_data['type'] = 'video'
                else:
                    validated_data['type'] = 'image'
            else:
                validated_data['type'] = 'text'
        else:
            # Multiple items = carousel
            validated_data['type'] = 'carousel'
        
        # Create post
        post = Post.objects.create(**validated_data)
        
        current_order = 0
        
        # Create media objects from files
        for file in media_files:
            media_type = 'video' if file.content_type.startswith('video') else 'image'
            media = PostMedia.objects.create(
                post=post,
                media_type=media_type,
                file=file,
                order=current_order
            )
            current_order += 1
            
            # Trigger background processing
            if media_type == 'image':
                generate_thumbnail.delay(media.id)
            elif media_type == 'video':
                process_video_metadata.delay(media.id)
        
        # Create text slide objects
        for slide_data in text_slides:
            order = slide_data.get('order', current_order)
            media = PostMedia.objects.create(
                post=post,
                media_type='text',
                text_content=slide_data['content'],
                background_color=slide_data.get('background_color', '#4A90E2'),
                text_color=slide_data.get('text_color', '#ffffff'),
                order=order
            )
            current_order += 1
            
            # Generate image for text slide
            generate_text_slide_image.delay(media.id)
        
        # Extract and create tags
        hashtags = self.extract_hashtags(caption)
        for tag_name in hashtags:
            tag, created = Tag.objects.get_or_create(name=tag_name)
            if not created:
                tag.usage_count += 1
                tag.save()
            else:
                tag.usage_count = 1
                tag.save()
            PostTag.objects.create(post=post, tag=tag)
        
        return post
    
    def update(self, instance, validated_data):
        validated_data.pop('media_files', None)  # Can't update media
        validated_data.pop('text_slides', None)  # Can't update text slides
        
        # If caption is updated, mark as edited and update tags
        if 'caption' in validated_data:
            old_caption = instance.caption
            new_caption = validated_data['caption']
            
            if old_caption != new_caption:
                instance.is_edited = True
                
                # Update tags
                old_tags = self.extract_hashtags(old_caption)
                new_tags = self.extract_hashtags(new_caption)
                
                # Remove old tags
                for tag_name in set(old_tags) - set(new_tags):
                    try:
                        tag = Tag.objects.get(name=tag_name)
                        PostTag.objects.filter(post=instance, tag=tag).delete()
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
                    else:
                        tag.usage_count = 1
                        tag.save()
                    PostTag.objects.get_or_create(post=instance, tag=tag)
        
        return super().update(instance, validated_data)
    
    def get_mentions(self, obj):
        """Get all mentions in this post"""
        content_type = ContentType.objects.get_for_model(Post)
        mentions = Mention.objects.filter(
            content_type=content_type,
            object_id=obj.id
        ).select_related('mentioned_user', 'mentioned_by')
        return MentionSerializer(mentions, many=True).data
    
    # UPDATE your create method:
    def create(self, validated_data):
        content = validated_data.get('content', '')
        post = super().create(validated_data)
        self._create_mentions(post, content, validated_data['user'])
        return post
    
    # UPDATE your update method:
    def update(self, instance, validated_data):
        content = validated_data.get('content')
        
        if content and content != instance.content:
            content_type = ContentType.objects.get_for_model(Post)
            Mention.objects.filter(
                content_type=content_type,
                object_id=instance.id
            ).delete()
            self._create_mentions(instance, content, instance.user)
        
        return super().update(instance, validated_data)
    
    # ADD this helper method:
    def _create_mentions(self, post, content, mentioned_by):
        """Helper method to create mention objects from content"""
        mention_pattern = r'@(\w+)'
        usernames = re.findall(mention_pattern, content)
        
        if not usernames:
            return
        
        mentioned_users = User.objects.filter(username__in=usernames)
        content_type = ContentType.objects.get_for_model(Post)
        
        mentions_to_create = []
        for user in mentioned_users:
            position = content.find(f'@{user.username}')
            mentions_to_create.append(
                Mention(
                    mentioned_user=user,
                    mentioned_by=mentioned_by,
                    content_type=content_type,
                    object_id=post.id,
                    position=position
                )
            )
        
        if mentions_to_create:
            Mention.objects.bulk_create(mentions_to_create, ignore_conflicts=True)


class PostListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for feed/list views"""
    user = UserMiniSerializer(read_only=True)
    first_media = serializers.SerializerMethodField()
    media_count = serializers.SerializerMethodField()
    is_liked = serializers.SerializerMethodField()
    
    class Meta:
        model = Post
        fields = [
            'id', 'user', 'type', 'caption', 'likes_count', 'comments_count',
            'first_media', 'media_count', 'is_liked', 'created_at'
        ]
    
    def get_first_media(self, obj):
        media = obj.media.first()
        if media:
            data = {
                'id': media.id,
                'media_type': media.media_type,
            }
            
            if media.media_type == 'text':
                data['text_content'] = media.text_content
                data['background_color'] = media.background_color
                data['file'] = media.file.url if media.file else None
                data['thumbnail'] = media.thumbnail.url if media.thumbnail else None
            else:
                data['file'] = media.file.url if media.file else None
                data['thumbnail'] = media.thumbnail.url if media.thumbnail else None
            
            return data
        return None
    
    def get_media_count(self, obj):
        """Return total number of media items for carousel indicator"""
        return obj.media.count()
    
    def get_is_liked(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return Like.objects.filter(
                user=request.user,
                target_type='post',
                target_id=obj.id
            ).exists()
        return False
    

class MentionSerializer(serializers.ModelSerializer):
    """Serializer for Mention model"""
    mentioned_user = serializers.SerializerMethodField()
    mentioned_by = serializers.SerializerMethodField()
    
    class Meta:
        model = Mention
        fields = ['id', 'mentioned_user', 'mentioned_by', 'position', 'created_at']
        read_only_fields = ['id', 'created_at']
    
    def get_mentioned_user(self, obj):
        user = obj.mentioned_user
        return {
            'id': obj.mentioned_user.id,
            'username': obj.mentioned_user.username,
            'display_name': getattr(obj.mentioned_user, 'display_name', ''),
            'avatar': user.profile.avatar.url if hasattr(user, 'profile') and user.profile.avatar else None
        }
    
    def get_mentioned_by(self, obj):
        user = obj.mentioned_by
        return {
            'id': obj.mentioned_by.id,
            'username': obj.mentioned_by.username,
            'display_name': getattr(obj.mentioned_by, 'display_name', ''),
            'avatar': getattr(obj.mentioned_by, 'avatar', None)
        }