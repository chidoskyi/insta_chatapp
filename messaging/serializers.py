from rest_framework import serializers
from django.contrib.auth import get_user_model
from django.utils import timezone

from messaging.services.presence_service import presence_service
from .models import (
    Call, CallParticipant, Conversation, ConversationMember, Message, MessageRead,
    MessageReaction, StarredMessage, BlockedUser, GroupInviteLink
)

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user info for nested serialization"""
    avatar = serializers.SerializerMethodField()
    is_online = serializers.SerializerMethodField()
    last_seen = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'email_verified', 'avatar', 'is_online', 'last_seen']

    def get_avatar(self, obj):
        if hasattr(obj, 'profile') and obj.profile.avatar:
            avatar_field = obj.profile.avatar.url
        else:
            return None

        if avatar_field.startswith(('http://', 'https://')):
            return avatar_field

        request = self.context.get('request')
        if request:
            return request.build_absolute_uri(avatar_field)

        from django.conf import settings
        if hasattr(settings, 'BASE_URL') and settings.BASE_URL:
            base_url = settings.BASE_URL.rstrip('/')
            avatar_path = avatar_field.lstrip('/')
            return f"{base_url}/{avatar_path}"
        
        return avatar_field
    
    def get_is_online(self, obj):
        """Check if user is online via Redis"""
        return presence_service.is_user_online(str(obj.id))

    def get_last_seen(self, obj):
        """Get user's last seen text"""
        return presence_service.get_last_seen_text(str(obj.id))


class MessageReactionSerializer(serializers.ModelSerializer):
    """Serializer for message reactions"""
    user = UserMiniSerializer(read_only=True)
    
    class Meta:
        model = MessageReaction
        fields = ['id', 'user', 'emoji', 'created_at']


class MessageReadSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    
    class Meta:
        model = MessageRead
        fields = ['user', 'read_at']


class MessageSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    reply_to_message = serializers.SerializerMethodField()
    read_by = MessageReadSerializer(many=True, read_only=True)
    reactions = MessageReactionSerializer(many=True, read_only=True)
    is_delivered = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    status = serializers.SerializerMethodField()
    is_starred_by_me = serializers.SerializerMethodField()
    forwarded_from_message = serializers.SerializerMethodField()
    media_url = serializers.SerializerMethodField()
    thumbnail_url = serializers.SerializerMethodField()
    
    class Meta:
        model = Message
        fields = [
            'id', 'conversation', 'sender', 'message_type', 'body', 
            'media', 'media_url', 'thumbnail_url', 'media_duration', 'media_size',
            'location_latitude', 'location_longitude', 'location_name',
            'reply_to', 'reply_to_message', 'forwarded_from', 'forwarded_from_message',
            'forward_count', 'is_edited', 'is_deleted', 'deleted_for_everyone',
            'reactions', 'read_by', 'is_delivered', 'is_read', 'status',
            'is_starred_by_me', 'created_at', 'updated_at', 'deleted_at'
        ]
        read_only_fields = ['id', 'sender', 'is_edited', 'created_at', 'updated_at']
    
    def get_media_url(self, obj):
        """Get absolute URL for media file"""
        if obj.media:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.media.url)
            return obj.media.url
        return None
    
    def get_thumbnail_url(self, obj):
        """Get absolute URL for thumbnail"""
        if obj.media_thumbnail:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.media_thumbnail.url)
            return obj.media_thumbnail.url
        return None
    
    def get_reply_to_message(self, obj):
        if obj.reply_to and not obj.reply_to.deleted_for_everyone:
            return {
                'id': str(obj.reply_to.id),  # ← FIX: Convert UUID to string
                'sender': UserMiniSerializer(obj.reply_to.sender, context=self.context).data,
                'body': obj.reply_to.body[:100] if obj.reply_to.body else '',
                'message_type': obj.reply_to.message_type,
                'created_at': obj.reply_to.created_at.isoformat(),  # ← FIX: Convert datetime to string
                'is_deleted': obj.reply_to.is_deleted
            }
        return None
    
    def get_forwarded_from_message(self, obj):
        if obj.forwarded_from:
            return {
                'id': str(obj.forwarded_from.id),  # ← FIX: Convert UUID to string
                'sender': UserMiniSerializer(obj.forwarded_from.sender, context=self.context).data,
            }
        return None
    
    def get_is_read(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated and obj.sender != request.user:
            return MessageRead.objects.filter(message=obj, user=request.user).exists()
        return True

    def get_is_delivered(self, obj):
        """Check if message has been delivered to at least one recipient"""
        # For the sender: check if ANY other member has received it
        request = self.context.get('request')
        
        if not request or not request.user.is_authenticated:
            # WebSocket context - calculate based on delivered_to count
            return obj.delivered_to.exclude(id=obj.sender.id).exists()
        
        if obj.sender == request.user:
            # Sender checking their own message
            # Return True if any recipient has received it
            conversation = obj.conversation
            other_members = conversation.members.exclude(user=request.user).filter(left_at__isnull=True)
            
            if other_members.count() == 0:
                return False
            
            # Check if at least ONE recipient has received it
            return any(
                obj.delivered_to.filter(id=member.user.id).exists()
                for member in other_members
            )
        else:
            # Recipient checking if they've received it
            return obj.delivered_to.filter(id=request.user.id).exists()

    def get_status(self, obj):
        """Calculate message status: sent, delivered, read"""
        request = self.context.get('request')
        
        # Only show status for messages you sent
        if not request or not request.user.is_authenticated:
            # WebSocket context - calculate based on data
            if obj.read_by.exclude(user=obj.sender).exists():
                return 'read'
            elif obj.delivered_to.exclude(id=obj.sender.id).exists():
                return 'delivered'
            return 'sent'
        
        if obj.sender != request.user:
            # Not the sender, don't show status
            return 'sent'
        
        conversation = obj.conversation
        other_members = conversation.members.exclude(user=request.user).filter(left_at__isnull=True)
        
        if other_members.count() == 0:
            return 'sent'
        
        # Check if ANY member has read (for groups, one blue check is enough to show read)
        any_read = any(
            MessageRead.objects.filter(message=obj, user=member.user).exists()
            for member in other_members
        )
        
        if any_read:
            return 'read'
        
        # Check if ANY member has received
        any_delivered = any(
            obj.delivered_to.filter(id=member.user.id).exists()
            for member in other_members
        )
        
        if any_delivered:
            return 'delivered'
        
        return 'sent'
    
    def get_is_starred_by_me(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            return StarredMessage.objects.filter(
                user=request.user, 
                message=obj
            ).exists()
        return False


        
class MessageCreateSerializer(serializers.ModelSerializer):
    media_file = serializers.FileField(write_only=True, required=False)
    
    class Meta:
        model = Message
        fields = [
            'body', 'message_type', 'media_file', 'reply_to', 
            'location_latitude', 'location_longitude', 'location_name'
        ]
    
    def validate(self, attrs):
        message_type = attrs.get('message_type', 'text')
        body = attrs.get('body', '')
        media_file = self.initial_data.get('media_file')
        
        # Text messages must have body
        if message_type == 'text' and not body.strip() and not media_file:
            raise serializers.ValidationError("Text message must have body or media")
        
        # Location messages must have coordinates
        if message_type == 'location':
            if not attrs.get('location_latitude') or not attrs.get('location_longitude'):
                raise serializers.ValidationError("Location messages must have coordinates")
        
        return attrs


class ConversationMemberSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    unread_count = serializers.SerializerMethodField()
    
    class Meta:
        model = ConversationMember
        fields = [
            'id', 'user', 'is_admin', 'is_muted', 'is_pinned', 'is_archived',
            'last_read_at', 'joined_at', 'unread_count', 'is_active',
            'show_last_seen', 'show_online_status'
        ]
    
    def get_unread_count(self, obj):
        return obj.get_unread_count()


class ConversationSerializer(serializers.ModelSerializer):
    members = ConversationMemberSerializer(many=True, read_only=True)
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_user = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()
    online_members = serializers.SerializerMethodField()
    typing_users = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = [
            'id', 'type', 'name', 'description', 'icon', 'icon_url',
            'only_admins_can_send', 'members', 'last_message',
            'unread_count', 'other_user', 'online_members', 'typing_users',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']
    
    def get_icon_url(self, obj):
        if obj.icon:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.icon.url)
            return obj.icon.url
        return None
    
    def get_last_message(self, obj):
        last_message = obj.get_last_message()
        if last_message:
            return MessageSerializer(last_message, context=self.context).data
        return None
    
    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            member = obj.members.filter(user=request.user).first()
            if member:
                return member.get_unread_count()
        return 0
    
    def get_other_user(self, obj):
        """For DM, return the other user"""
        request = self.context.get('request')
        if obj.type == 'direct' and request and request.user.is_authenticated:
            other = obj.get_other_user(request.user)
            if other:
                return UserMiniSerializer(other, context=self.context).data
        return None
    
    def get_online_members(self, obj):
        """Get list of online member IDs"""
        member_ids = obj.members.filter(
            left_at__isnull=True
        ).values_list('user_id', flat=True)
        
        return presence_service.get_online_users_in_conversation(
            str(obj.id), 
            [str(uid) for uid in member_ids]
        )
    
    def get_typing_users(self, obj):
        """Get list of users currently typing"""
        typing_user_ids = presence_service.get_typing_users(str(obj.id))
        return typing_user_ids


class ConversationListSerializer(serializers.ModelSerializer):
    """Lightweight serializer for conversation list"""
    last_message = serializers.SerializerMethodField()
    unread_count = serializers.SerializerMethodField()
    other_user = serializers.SerializerMethodField()
    icon_url = serializers.SerializerMethodField()
    is_pinned = serializers.SerializerMethodField()
    is_archived = serializers.SerializerMethodField()
    is_muted = serializers.SerializerMethodField()
    
    class Meta:
        model = Conversation
        fields = [
            'id', 'type', 'name', 'icon_url', 'last_message', 'unread_count',
            'other_user', 'is_pinned', 'is_archived', 'is_muted', 'updated_at'
        ]
    
    def get_icon_url(self, obj):
        if obj.icon:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.icon.url)
            return obj.icon.url
        return None
    
    def get_last_message(self, obj):
        last_message = obj.get_last_message()
        if last_message:
            return {
                'id': last_message.id,
                'sender': UserMiniSerializer(last_message.sender, context=self.context).data,
                'body': last_message.body[:100] if last_message.body else '',
                'message_type': last_message.message_type,
                'created_at': last_message.created_at,
                'is_deleted': last_message.is_deleted,
                'deleted_for_everyone': last_message.deleted_for_everyone
            }
        return None
    
    def get_unread_count(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            member = obj.members.filter(user=request.user).first()
            if member:
                return member.get_unread_count()
        return 0
    
    def get_other_user(self, obj):
        request = self.context.get('request')
        if obj.type == 'direct' and request and request.user.is_authenticated:
            other = obj.get_other_user(request.user)
            if other:
                return UserMiniSerializer(other, context=self.context).data
        return None
    
    def get_is_pinned(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            member = obj.members.filter(user=request.user).first()
            return member.is_pinned if member else False
        return False
    
    def get_is_archived(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            member = obj.members.filter(user=request.user).first()
            return member.is_archived if member else False
        return False
    
    def get_is_muted(self, obj):
        request = self.context.get('request')
        if request and request.user.is_authenticated:
            member = obj.members.filter(user=request.user).first()
            return member.is_muted if member else False
        return False


class ConversationCreateSerializer(serializers.Serializer):
    """Create a new conversation"""
    type = serializers.ChoiceField(choices=['direct', 'group'], default='direct')
    name = serializers.CharField(required=False, allow_blank=True, max_length=100)
    description = serializers.CharField(required=False, allow_blank=True, max_length=500)
    icon = serializers.ImageField(required=False)
    user_ids = serializers.ListField(
        child=serializers.UUIDField(),
        min_length=1
    )
    
    def validate_user_ids(self, value):
        if User.objects.filter(id__in=value).count() != len(value):
            raise serializers.ValidationError("One or more users do not exist")
        return value
    
    def validate(self, attrs):
        if attrs['type'] == 'direct' and len(attrs['user_ids']) != 1:
            raise serializers.ValidationError("Direct messages must have exactly one other user")
        if attrs['type'] == 'group' and len(attrs['user_ids']) < 1:
            raise serializers.ValidationError("Group chats must have at least 1 other user")
        return attrs


class GroupInviteLinkSerializer(serializers.ModelSerializer):
    created_by = UserMiniSerializer(read_only=True)
    is_valid = serializers.SerializerMethodField()
    invite_url = serializers.SerializerMethodField()
    
    class Meta:
        model = GroupInviteLink
        fields = [
            'id', 'code', 'created_by', 'is_active', 'expires_at',
            'max_uses', 'use_count', 'is_valid', 'invite_url', 'created_at'
        ]
        read_only_fields = ['id', 'code', 'use_count', 'created_at']
    
    def get_is_valid(self, obj):
        return obj.is_valid()
    
    def get_invite_url(self, obj):
        request = self.context.get('request')
        if request:
            from django.conf import settings
            base_url = getattr(settings, 'FRONTEND_URL', request.build_absolute_uri('/'))
            return f"{base_url.rstrip('/')}/invite/{obj.code}"
        return None


class StarredMessageSerializer(serializers.ModelSerializer):
    message = MessageSerializer(read_only=True)
    
    class Meta:
        model = StarredMessage
        fields = ['id', 'message', 'starred_at']


class BlockedUserSerializer(serializers.ModelSerializer):
    blocked_user = UserMiniSerializer(source='blocked', read_only=True)
    
    class Meta:
        model = BlockedUser
        fields = ['id', 'blocked_user', 'blocked_at']


class CallParticipantSerializer(serializers.ModelSerializer):
    user = UserMiniSerializer(read_only=True)
    
    class Meta:
        model = CallParticipant
        fields = [
            'id', 'user', 'status', 'ice_candidates',
            'invited_at', 'joined_at', 'left_at'
        ]
        read_only_fields = ['id', 'invited_at']


class CallSerializer(serializers.ModelSerializer):
    caller = UserMiniSerializer(read_only=True)
    participants = CallParticipantSerializer(source='call_participants', many=True, read_only=True)
    duration_display = serializers.SerializerMethodField()
    
    class Meta:
        model = Call
        fields = [
            'id', 'conversation', 'caller', 'call_type', 'status',
            'offer_sdp', 'answer_sdp', 'participants',
            'initiated_at', 'answered_at', 'ended_at',
            'duration', 'duration_display'
        ]
        read_only_fields = ['id', 'caller', 'duration', 'initiated_at']
    
    def get_duration_display(self, obj):
        if obj.duration:
            minutes = obj.duration // 60
            seconds = obj.duration % 60
            return f"{minutes:02d}:{seconds:02d}"
        return "00:00"


class CallInitiateSerializer(serializers.Serializer):
    """Initiate a call"""
    conversation_id = serializers.UUIDField()
    call_type = serializers.ChoiceField(choices=['audio', 'video'])
    offer_sdp = serializers.CharField(required=False, allow_blank=True)
    
    def validate_conversation_id(self, value):
        from .models import Conversation
        if not Conversation.objects.filter(id=value).exists():
            raise serializers.ValidationError("Conversation does not exist")
        return value


class CallAnswerSerializer(serializers.Serializer):
    """Answer a call"""
    answer_sdp = serializers.CharField()


class CallUpdateSerializer(serializers.Serializer):
    """Update call status or add ICE candidates"""
    status = serializers.ChoiceField(
        choices=['ringing', 'answered', 'rejected', 'ended'],
        required=False
    )
    ice_candidates = serializers.ListField(
        child=serializers.DictField(),
        required=False
    )

    def validate(self, attrs):
        if 'status' not in attrs and 'ice_candidates' not in attrs:
            raise serializers.ValidationError("At least one of 'status' or 'ice_candidates' must be provided")
        return attrs


