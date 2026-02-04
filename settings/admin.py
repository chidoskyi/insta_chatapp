from django.contrib import admin
from .models import (
    PrivacySettings,
    BlockedUser,
    MutedUser,
    RestrictedUser,
    ActivityLog,
    CloseFriendsList
)


@admin.register(PrivacySettings)
class PrivacySettingsAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_private', 'show_activity_status', 'allow_comments', 'updated_at']
    list_filter = ['is_private', 'show_activity_status', 'allow_comments']
    search_fields = ['user__username']
    raw_id_fields = ['user']
    filter_horizontal = ['hide_story_from']
    readonly_fields = ['created_at', 'updated_at']
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Account Privacy', {
            'fields': ('is_private', 'show_activity_status')
        }),
        ('Story Settings', {
            'fields': ('allow_story_sharing', 'allow_story_replies', 'hide_story_from')
        }),
        ('Post Settings', {
            'fields': ('allow_comments', 'allow_comment_likes', 'hide_like_counts')
        }),
        ('Tagging & Mentions', {
            'fields': ('allow_tags', 'manual_tag_approval', 'allow_mentions', 'mentions_from')
        }),
        ('Messages', {
            'fields': ('allow_messages_from',)
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(BlockedUser)
class BlockedUserAdmin(admin.ModelAdmin):
    list_display = ['blocker', 'blocked', 'blocked_at', 'reason']
    list_filter = ['blocked_at']
    search_fields = ['blocker__username', 'blocked__username']
    raw_id_fields = ['blocker', 'blocked']
    readonly_fields = ['blocked_at']
    ordering = ['-blocked_at']


@admin.register(MutedUser)
class MutedUserAdmin(admin.ModelAdmin):
    list_display = ['muter', 'muted', 'mute_posts', 'mute_stories', 'mute_reels', 'muted_at']
    list_filter = ['mute_posts', 'mute_stories', 'mute_reels', 'muted_at']
    search_fields = ['muter__username', 'muted__username']
    raw_id_fields = ['muter', 'muted']
    readonly_fields = ['muted_at']
    ordering = ['-muted_at']


@admin.register(RestrictedUser)
class RestrictedUserAdmin(admin.ModelAdmin):
    list_display = ['restrictor', 'restricted', 'restricted_at']
    list_filter = ['restricted_at']
    search_fields = ['restrictor__username', 'restricted__username']
    raw_id_fields = ['restrictor', 'restricted']
    readonly_fields = ['restricted_at']
    ordering = ['-restricted_at']


@admin.register(ActivityLog)
class ActivityLogAdmin(admin.ModelAdmin):
    list_display = ['user', 'action_type', 'ip_address', 'device', 'created_at']
    list_filter = ['action_type', 'created_at']
    search_fields = ['user__username', 'ip_address']
    raw_id_fields = ['user']
    readonly_fields = ['created_at']
    ordering = ['-created_at']
    
    def has_add_permission(self, request):
        return False


@admin.register(CloseFriendsList)
class CloseFriendsListAdmin(admin.ModelAdmin):
    list_display = ['user', 'close_friend', 'added_at']
    list_filter = ['added_at']
    search_fields = ['user__username', 'close_friend__username']
    raw_id_fields = ['user', 'close_friend']
    readonly_fields = ['added_at']
    ordering = ['-added_at']