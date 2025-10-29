from rest_framework import serializers
from django.contrib.auth import get_user_model
from .models import (
    PrivacySettings,
    BlockedUser,
    MutedUser,
    RestrictedUser,
    ActivityLog,
    CloseFriendsList
)

User = get_user_model()


class UserMiniSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'display_name', 'avatar', 'verified']
    
    def to_representation(self, instance):
        data = super().to_representation(instance)
        if hasattr(instance, 'profile') and instance.profile.avatar:
            data['avatar'] = instance.profile.avatar.url
        else:
            data['avatar'] = None
        return data


class PrivacySettingsSerializer(serializers.ModelSerializer):
    hide_story_from = UserMiniSerializer(many=True, read_only=True)
    hide_story_from_ids = serializers.ListField(
        child=serializers.IntegerField(),
        write_only=True,
        required=False
    )
    
    class Meta:
        model = PrivacySettings
        fields = [
            'is_private', 'show_activity_status',
            'allow_story_sharing', 'allow_story_replies', 'hide_story_from', 'hide_story_from_ids',
            'allow_comments', 'allow_comment_likes', 'hide_like_counts',
            'allow_tags', 'manual_tag_approval',
            'allow_mentions', 'mentions_from',
            'allow_messages_from',
            'updated_at'
        ]
        read_only_fields = ['updated_at']
    
    def update(self, instance, validated_data):
        hide_story_from_ids = validated_data.pop('hide_story_from_ids', None)
        
        # Update fields
        for attr, value in validated_data.items():
            setattr(instance, attr, value)
        instance.save()
        
        # Update hide_story_from list
        if hide_story_from_ids is not None:
            instance.hide_story_from.clear()
            users = User.objects.filter(id__in=hide_story_from_ids)
            instance.hide_story_from.set(users)
        
        return instance


class BlockedUserSerializer(serializers.ModelSerializer):
    blocked = UserMiniSerializer(read_only=True)
    blocked_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = BlockedUser
        fields = ['id', 'blocked', 'blocked_id', 'blocked_at', 'reason']
        read_only_fields = ['id', 'blocked_at']


class MutedUserSerializer(serializers.ModelSerializer):
    muted = UserMiniSerializer(read_only=True)
    muted_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = MutedUser
        fields = [
            'id', 'muted', 'muted_id',
            'mute_posts', 'mute_stories', 'mute_reels',
            'muted_at'
        ]
        read_only_fields = ['id', 'muted_at']


class RestrictedUserSerializer(serializers.ModelSerializer):
    restricted = UserMiniSerializer(read_only=True)
    restricted_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = RestrictedUser
        fields = ['id', 'restricted', 'restricted_id', 'restricted_at']
        read_only_fields = ['id', 'restricted_at']


class ActivityLogSerializer(serializers.ModelSerializer):
    class Meta:
        model = ActivityLog
        fields = [
            'id', 'action_type', 'ip_address', 'user_agent',
            'device', 'location', 'created_at'
        ]
        read_only_fields = ['id', 'created_at']


class CloseFriendsSerializer(serializers.ModelSerializer):
    close_friend = UserMiniSerializer(read_only=True)
    close_friend_id = serializers.IntegerField(write_only=True)
    
    class Meta:
        model = CloseFriendsList
        fields = ['id', 'close_friend', 'close_friend_id', 'added_at']
        read_only_fields = ['id', 'added_at']