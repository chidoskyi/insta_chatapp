from django.contrib import admin
from django.utils import timezone
from django.contrib.auth.models import Group as AuthGroup
from .models import (
    Conversation, ConversationMember, Message, MessageRead,
    MessageReaction, StarredMessage, BlockedUser, GroupInviteLink,
    TypingStatus, UserPresence, Call, CallParticipant
)
from messaging import models


class ConversationMemberInline(admin.TabularInline):
    """Inline for conversation members"""
    model = ConversationMember
    extra = 0
    readonly_fields = ('joined_at', 'left_at', 'last_read_at')
    fields = ('user', 'is_admin', 'is_muted', 'is_pinned', 'is_archived', 'last_read_at', 'joined_at', 'left_at')
    raw_id_fields = ('user',)


class MessageInline(admin.TabularInline):
    """Inline for messages in conversation"""
    model = Message
    extra = 0
    readonly_fields = ('created_at', 'updated_at', 'deleted_at')
    fields = ('sender', 'message_type', 'body', 'is_deleted', 'created_at')
    raw_id_fields = ('sender', 'reply_to', 'forwarded_from')
    
    def body_preview(self, obj):
        if obj.body:
            return obj.body[:50] + ('...' if len(obj.body) > 50 else '')
        return '-'
    body_preview.short_description = 'Message Preview'


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    list_display = ('id', 'type', 'name', 'member_count', 'last_message_time', 'created_by', 'created_at')
    list_filter = ('type', 'created_at', 'only_admins_can_send')
    search_fields = ('name', 'id', 'description', 'created_by__username', 'created_by__email')
    readonly_fields = ('id', 'created_at', 'updated_at', 'get_member_list', 'get_last_message_info')
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'type', 'name', 'description', 'icon', 'created_by', 'created_at', 'updated_at')
        }),
        ('Group Settings', {
            'fields': ('only_admins_can_send',),
            'classes': ('collapse',)
        }),
        ('Statistics', {
            'fields': ('get_member_list', 'get_last_message_info'),
            'classes': ('collapse',)
        }),
    )
    inlines = [ConversationMemberInline, MessageInline]
    
    def member_count(self, obj):
        return obj.members.filter(left_at__isnull=True).count()
    member_count.short_description = 'Members'
    
    def last_message_time(self, obj):
        last_message = obj.get_last_message()
        return last_message.created_at if last_message else None
    last_message_time.short_description = 'Last Message'
    
    def get_member_list(self, obj):
        members = obj.members.filter(left_at__isnull=True).select_related('user')
        member_list = ', '.join([member.user.username for member in members])
        return member_list or 'No active members'
    get_member_list.short_description = 'Active Members'
    
    def get_last_message_info(self, obj):
        last_message = obj.get_last_message()
        if last_message:
            return f"{last_message.sender.username}: {last_message.body[:100] if last_message.body else '[Media]'}"
        return 'No messages'
    get_last_message_info.short_description = 'Last Message'


@admin.register(ConversationMember)
class ConversationMemberAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'user', 'is_admin', 'is_muted', 'is_pinned', 'is_archived', 'is_active', 'joined_at')
    list_filter = ('is_admin', 'is_muted', 'is_pinned', 'is_archived', 'joined_at')
    search_fields = ('user__username', 'user__email', 'conversation__name', 'conversation__id')
    readonly_fields = ('joined_at', 'left_at', 'last_read_at')
    raw_id_fields = ('conversation', 'user')
    fieldsets = (
        ('Basic Information', {
            'fields': ('conversation', 'user', 'is_active', 'joined_at', 'left_at')
        }),
        ('Member Settings', {
            'fields': ('is_admin', 'is_muted', 'is_pinned', 'is_archived')
        }),
        ('Privacy Settings', {
            'fields': ('show_last_seen', 'show_online_status'),
            'classes': ('collapse',)
        }),
        ('Read Tracking', {
            'fields': ('last_read_at',),
            'classes': ('collapse',)
        }),
    )
    
    def is_active(self, obj):
        return obj.is_active
    is_active.boolean = True
    is_active.short_description = 'Active'


class MessageReadInline(admin.TabularInline):
    """Inline for message read receipts"""
    model = MessageRead
    extra = 0
    readonly_fields = ('read_at',)
    raw_id_fields = ('user',)


class MessageReactionInline(admin.TabularInline):
    """Inline for message reactions"""
    model = MessageReaction
    extra = 0
    readonly_fields = ('created_at',)
    raw_id_fields = ('user',)


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = ('id_short', 'conversation', 'sender', 'message_type', 'body_preview', 'is_deleted', 'created_at')
    list_filter = ('message_type', 'is_deleted', 'is_edited', 'deleted_for_everyone', 'created_at')
    search_fields = ('body', 'sender__username', 'conversation__name', 'conversation__id')
    readonly_fields = ('id', 'created_at', 'updated_at', 'deleted_at', 'get_reaction_summary', 'get_forward_count')
    raw_id_fields = ('conversation', 'sender', 'reply_to', 'forwarded_from')
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'conversation', 'sender', 'message_type', 'created_at', 'updated_at')
        }),
        ('Content', {
            'fields': ('body', 'media', 'media_thumbnail', 'media_duration', 'media_size')
        }),
        ('Location (if applicable)', {
            'fields': ('location_latitude', 'location_longitude', 'location_name'),
            'classes': ('collapse',)
        }),
        ('Message Context', {
            'fields': ('reply_to', 'forwarded_from', 'forward_count')
        }),
        ('Status', {
            'fields': ('is_edited', 'is_deleted', 'deleted_for_everyone', 'deleted_at', 'is_starred')
        }),
        ('Statistics', {
            'fields': ('get_reaction_summary', 'get_forward_count'),
            'classes': ('collapse',)
        }),
    )
    inlines = [MessageReadInline, MessageReactionInline]
    
    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = 'ID'
    
    def body_preview(self, obj):
        if obj.body:
            return obj.body[:50] + ('...' if len(obj.body) > 50 else '')
        return f'[{obj.message_type.upper()}]'
    body_preview.short_description = 'Message'
    
    def get_reaction_summary(self, obj):
        reactions = obj.reactions.values('emoji').annotate(count=models.Count('emoji'))
        if reactions:
            return ', '.join([f"{r['emoji']}: {r['count']}" for r in reactions])
        return 'No reactions'
    get_reaction_summary.short_description = 'Reactions Summary'
    
    def get_forward_count(self, obj):
        return obj.forwards.count()
    get_forward_count.short_description = 'Times Forwarded'


@admin.register(MessageReaction)
class MessageReactionAdmin(admin.ModelAdmin):
    list_display = ('message', 'user', 'emoji', 'created_at')
    list_filter = ('emoji', 'created_at')
    search_fields = ('message__id', 'user__username', 'emoji')
    readonly_fields = ('created_at',)
    raw_id_fields = ('message', 'user')


@admin.register(StarredMessage)
class StarredMessageAdmin(admin.ModelAdmin):
    list_display = ('user', 'message', 'starred_at')
    list_filter = ('starred_at',)
    search_fields = ('user__username', 'message__id')
    readonly_fields = ('starred_at',)
    raw_id_fields = ('user', 'message')


@admin.register(BlockedUser)
class BlockedUserAdmin(admin.ModelAdmin):
    list_display = ('blocker', 'blocked', 'blocked_at')
    list_filter = ('blocked_at',)
    search_fields = ('blocker__username', 'blocked__username')
    readonly_fields = ('blocked_at',)
    raw_id_fields = ('blocker', 'blocked')


@admin.register(GroupInviteLink)
class GroupInviteLinkAdmin(admin.ModelAdmin):
    list_display = ('code', 'conversation', 'created_by', 'is_active', 'is_valid', 'use_count', 'created_at')
    list_filter = ('is_active', 'created_at')
    search_fields = ('code', 'conversation__name', 'created_by__username')
    readonly_fields = ('code', 'created_at', 'use_count', 'is_valid_display')
    raw_id_fields = ('conversation', 'created_by')
    fieldsets = (
        ('Basic Information', {
            'fields': ('code', 'conversation', 'created_by', 'created_at')
        }),
        ('Usage Limits', {
            'fields': ('is_active', 'expires_at', 'max_uses', 'use_count')
        }),
        ('Status', {
            'fields': ('is_valid_display',),
        }),
    )
    
    def is_valid(self, obj):
        return obj.is_valid()
    is_valid.boolean = True
    is_valid.short_description = 'Valid'
    
    def is_valid_display(self, obj):
        if not obj.is_active:
            return "❌ Inactive"
        if obj.expires_at and timezone.now() > obj.expires_at:
            return "❌ Expired"
        if obj.max_uses and obj.use_count >= obj.max_uses:
            return f"❌ Max uses reached ({obj.use_count}/{obj.max_uses})"
        return "✅ Valid"
    is_valid_display.short_description = 'Link Status'


@admin.register(TypingStatus)
class TypingStatusAdmin(admin.ModelAdmin):
    list_display = ('conversation', 'user', 'is_active', 'started_at')
    list_filter = ('started_at',)
    search_fields = ('conversation__name', 'user__username')
    readonly_fields = ('started_at', 'is_active')
    raw_id_fields = ('conversation', 'user')


@admin.register(UserPresence)
class UserPresenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_online', 'last_seen', 'last_activity', 'online_status_privacy', 'last_seen_privacy')
    list_filter = ('is_online', 'show_online_status_to', 'show_last_seen_to')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('last_seen', 'last_activity', 'updated_at')
    raw_id_fields = ('user',)
    fieldsets = (
        ('Status', {
            'fields': ('user', 'is_online', 'last_seen', 'last_activity', 'updated_at')
        }),
        ('Privacy Settings', {
            'fields': ('show_online_status_to', 'show_last_seen_to')
        }),
    )
    
    def online_status_privacy(self, obj):
        return dict(obj._meta.get_field('show_online_status_to').choices).get(obj.show_online_status_to)
    online_status_privacy.short_description = 'Online Status Visible To'
    
    def last_seen_privacy(self, obj):
        return dict(obj._meta.get_field('show_last_seen_to').choices).get(obj.show_last_seen_to)
    last_seen_privacy.short_description = 'Last Seen Visible To'


class CallParticipantInline(admin.TabularInline):
    """Inline for call participants"""
    model = CallParticipant
    extra = 0
    readonly_fields = ('invited_at', 'joined_at', 'left_at')
    raw_id_fields = ('user',)


@admin.register(Call)
class CallAdmin(admin.ModelAdmin):
    list_display = ('id_short', 'conversation', 'caller', 'call_type', 'status', 'duration', 'initiated_at')
    list_filter = ('call_type', 'status', 'initiated_at')
    search_fields = ('conversation__name', 'caller__username', 'id')
    readonly_fields = (
        'id', 'initiated_at', 'answered_at', 'ended_at', 
        'duration', 'participant_count', 'offer_sdp_preview', 'answer_sdp_preview'
    )
    raw_id_fields = ('conversation', 'caller')
    fieldsets = (
        ('Basic Information', {
            'fields': ('id', 'conversation', 'caller', 'call_type', 'status', 'duration')
        }),
        ('Timing', {
            'fields': ('initiated_at', 'answered_at', 'ended_at')
        }),
        ('WebRTC Data', {
            'fields': ('offer_sdp_preview', 'answer_sdp_preview'),
            'classes': ('collapse',)
        }),
        ('Participants', {
            'fields': ('participant_count',),
        }),
    )
    inlines = [CallParticipantInline]
    
    def id_short(self, obj):
        return str(obj.id)[:8]
    id_short.short_description = 'ID'
    
    def participant_count(self, obj):
        return obj.participants.count()
    participant_count.short_description = 'Total Participants'
    
    def offer_sdp_preview(self, obj):
        if obj.offer_sdp:
            return obj.offer_sdp[:100] + ('...' if len(obj.offer_sdp) > 100 else '')
        return '-'
    offer_sdp_preview.short_description = 'Offer SDP (Preview)'
    
    def answer_sdp_preview(self, obj):
        if obj.answer_sdp:
            return obj.answer_sdp[:100] + ('...' if len(obj.answer_sdp) > 100 else '')
        return '-'
    answer_sdp_preview.short_description = 'Answer SDP (Preview)'


@admin.register(CallParticipant)
class CallParticipantAdmin(admin.ModelAdmin):
    list_display = ('call', 'user', 'status', 'invited_at', 'joined_at')
    list_filter = ('status', 'invited_at')
    search_fields = ('call__id', 'user__username')
    readonly_fields = ('invited_at', 'joined_at', 'left_at')
    raw_id_fields = ('call', 'user')


# Unregister default Group if not needed
# admin.site.unregister(AuthGroup)

# Custom admin site settings
admin.site.site_header = 'Messaging System Administration'
admin.site.site_title = 'Messaging Admin'
admin.site.index_title = 'Messaging System Management'