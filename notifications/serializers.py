from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Notification, NotificationPreference, NotificationGroup

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user info for nested serialization"""
    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'avatar', 'verified']


class NotificationSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    time_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id', 'sender', 'notification_type', 'target_type', 'target_id',
            'payload', 'message', 'is_read', 'read_at', 'created_at', 'time_ago'
        ]
        read_only_fields = ['id', 'sender', 'created_at', 'read_at']
    
    def get_time_ago(self, obj):
        """Return human-readable time difference"""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        diff = now - obj.created_at
        
        seconds = diff.total_seconds()
        
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m ago"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h ago"
        elif seconds < 604800:
            days = int(seconds / 86400)
            return f"{days}d ago"
        else:
            weeks = int(seconds / 604800)
            return f"{weeks}w ago"


class NotificationGroupSerializer(serializers.ModelSerializer):
    """Grouped notifications serializer"""
    senders = UserMiniSerializer(many=True, read_only=True)
    sender_preview = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()
    
    class Meta:
        model = NotificationGroup
        fields = [
            'id', 'notification_type', 'target_type', 'target_id',
            'senders', 'sender_preview', 'count', 'is_read',
            'message', 'last_updated', 'created_at'
        ]
    
    def get_sender_preview(self, obj):
        """Get preview of senders (first few)"""
        senders = obj.senders.all()[:3]
        return UserMiniSerializer(senders, many=True).data
    
    def get_message(self, obj):
        """Generate message for grouped notification"""
        senders = obj.senders.all()
        count = senders.count()
        
        if count == 0:
            return ""
        elif count == 1:
            sender = senders[0]
            return self._get_single_message(sender, obj)
        elif count == 2:
            return f"{senders[0].username} and {senders[1].username} {self._get_action(obj)}"
        else:
            return f"{senders[0].username} and {count - 1} others {self._get_action(obj)}"
    
    def _get_single_message(self, sender, obj):
        """Get message for single sender"""
        action = self._get_action(obj)
        return f"{sender.username} {action}"
    
    def _get_action(self, obj):
        """Get action text based on notification type"""
        type_map = {
            'like_post': 'liked your post',
            'like_comment': 'liked your comment',
            'comment': 'commented on your post',
            'reply': 'replied to your comment',
            'follow': 'started following you',
            'mention': 'mentioned you',
            'story_view': 'viewed your story',
        }
        return type_map.get(obj.notification_type, 'interacted with your content')


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = NotificationPreference
        fields = [
            'email_on_like', 'email_on_comment', 'email_on_follow', 'email_on_mention',
            'push_on_like', 'push_on_comment', 'push_on_follow', 'push_on_mention', 'push_on_story_view',
            'notify_on_like', 'notify_on_comment', 'notify_on_follow', 'notify_on_mention', 'notify_on_story_view',
            'pause_all'
        ]


class NotificationCreateSerializer(serializers.Serializer):
    """Internal serializer for creating notifications"""
    recipient_id = serializers.IntegerField()
    sender_id = serializers.IntegerField(required=False, allow_null=True)
    notification_type = serializers.ChoiceField(choices=Notification.NOTIFICATION_TYPES)
    target_type = serializers.CharField(required=False, allow_blank=True)
    target_id = serializers.IntegerField(required=False, allow_null=True)
    payload = serializers.JSONField(required=False, default=dict)
    message = serializers.CharField(required=False, allow_blank=True)