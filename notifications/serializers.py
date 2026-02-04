from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import Notification, NotificationPreference, NotificationGroup

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    """Minimal user info for nested serialization"""
    avatar = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'email_verified', 'avatar']
    
    def get_avatar(self, obj):
        if hasattr(obj, 'profile') and obj.profile.avatar:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(obj.profile.avatar.url)
            return obj.profile.avatar.url
        return None


class NotificationSerializer(serializers.ModelSerializer):
    sender = UserMiniSerializer(read_only=True)
    time_ago = serializers.SerializerMethodField()
    conversation_id = serializers.SerializerMethodField()
    message_preview = serializers.SerializerMethodField()
    
    class Meta:
        model = Notification
        fields = [
            'id', 'sender', 'notification_type', 'target_type', 'target_id',
            'payload', 'message', 'is_read', 'read_at', 'created_at', 
            'time_ago', 'conversation_id', 'message_preview'
        ]
        read_only_fields = ['id', 'sender', 'created_at', 'read_at']
    
    def get_time_ago(self, obj):
        """Return human-readable time difference (WhatsApp style)"""
        from django.utils import timezone
        from datetime import timedelta
        
        now = timezone.now()
        diff = now - obj.created_at
        
        seconds = diff.total_seconds()
        
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds / 60)
            return f"{minutes}m"
        elif seconds < 86400:
            hours = int(seconds / 3600)
            return f"{hours}h"
        elif seconds < 604800:  # Less than a week
            days = int(seconds / 86400)
            if days == 1:
                return "yesterday"
            return f"{days}d"
        elif seconds < 2592000:  # Less than 30 days
            weeks = int(seconds / 604800)
            return f"{weeks}w"
        else:
            # Show actual date for older notifications
            return obj.created_at.strftime("%b %d")
    
    def get_conversation_id(self, obj):
        """Get conversation ID from payload"""
        return obj.payload.get('conversation_id')
    
    def get_message_preview(self, obj):
        """Get message preview from payload"""
        if obj.notification_type in ['message', 'group_message']:
            # Check if user wants message preview
            recipient = obj.recipient
            if hasattr(recipient, 'notification_preferences'):
                if not recipient.notification_preferences.show_message_preview:
                    return "New message"
            
            return obj.payload.get('body', '')[:100]
        
        return None


class NotificationGroupSerializer(serializers.ModelSerializer):
    """Grouped notifications serializer (WhatsApp style)"""
    senders = UserMiniSerializer(many=True, read_only=True)
    sender_preview = serializers.SerializerMethodField()
    message = serializers.SerializerMethodField()
    time_ago = serializers.SerializerMethodField()
    
    class Meta:
        model = NotificationGroup
        fields = [
            'id', 'notification_type', 'target_type', 'target_id',
            'senders', 'sender_preview', 'count', 'is_read',
            'message', 'last_updated', 'created_at', 'time_ago'
        ]
    
    def get_sender_preview(self, obj):
        """Get preview of senders (first few)"""
        senders = obj.senders.all()[:3]
        return UserMiniSerializer(senders, many=True, context=self.context).data
    
    def get_message(self, obj):
        """Generate message for grouped notification (WhatsApp style)"""
        return obj.get_preview_message()
    
    def get_time_ago(self, obj):
        """Human-readable time for last update"""
        from django.utils import timezone
        
        now = timezone.now()
        diff = now - obj.last_updated
        seconds = diff.total_seconds()
        
        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            return f"{int(seconds / 60)}m"
        elif seconds < 86400:
            return f"{int(seconds / 3600)}h"
        else:
            days = int(seconds / 86400)
            return f"{days}d" if days < 7 else obj.last_updated.strftime("%b %d")


class NotificationPreferenceSerializer(serializers.ModelSerializer):
    is_muted = serializers.SerializerMethodField()
    muted_until = serializers.SerializerMethodField()
    
    class Meta:
        model = NotificationPreference
        fields = [
            # Message notifications
            'notify_on_message', 'notify_on_group_message', 'notify_on_reaction',
            'notify_on_reply', 'notify_on_mention', 'notify_on_call',
            
            # Push notifications
            'push_on_message', 'push_on_group_message', 'push_on_reaction',
            'push_on_reply', 'push_on_mention', 'push_on_call',
            
            # Email notifications
            'email_on_message', 'email_on_group_message',
            
            # Sound settings
            'message_sound_enabled', 'group_message_sound_enabled', 'call_sound_enabled',
            'message_tone', 'notification_tone', 'ringtone',
            
            # Vibration
            'vibrate_on_message', 'vibrate_on_call',
            
            # Preview settings
            'show_message_preview', 'show_sender_name',
            
            # General
            'pause_all', 'pause_until', 'is_muted', 'muted_until',
            
            # Visual
            'notification_light_enabled', 'notification_light_color',
            'high_priority_notifications',
        ]
    
    def get_is_muted(self, obj):
        """Check if notifications are currently muted"""
        return obj.is_currently_muted()
    
    def get_muted_until(self, obj):
        """Get muted until time in human-readable format"""
        if obj.pause_until:
            return obj.pause_until.isoformat()
        return None


class NotificationStatsSerializer(serializers.Serializer):
    """Statistics about notifications"""
    total = serializers.IntegerField()
    unread = serializers.IntegerField()
    read = serializers.IntegerField()
    by_type = serializers.DictField()
    recent_count = serializers.IntegerField()  # Count from last 24 hours


class NotificationCreateSerializer(serializers.Serializer):
    """Internal serializer for creating notifications via API (admin/testing)"""
    recipient_id = serializers.UUIDField()
    sender_id = serializers.UUIDField(required=False, allow_null=True)
    notification_type = serializers.ChoiceField(choices=Notification.NOTIFICATION_TYPES)
    target_type = serializers.CharField(required=False, allow_blank=True)
    target_id = serializers.UUIDField(required=False, allow_null=True)
    payload = serializers.JSONField(required=False, default=dict)
    message = serializers.CharField(required=False, allow_blank=True)