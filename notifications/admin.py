from django.contrib import admin
from django.utils.html import format_html
from django.utils import timezone
from datetime import timedelta
from .models import Notification, NotificationPreference, NotificationGroup


class NotificationAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'recipient', 'sender_preview', 'notification_type_formatted',
        'target_preview', 'message_preview', 'is_read', 'created_ago',
        'created_at'
    )
    list_filter = (
        'notification_type', 'is_read', 'created_at', 'target_type'
    )
    search_fields = (
        'recipient__username', 'recipient__email',
        'sender__username', 'sender__email',
        'message', 'notification_type'
    )
    readonly_fields = (
        'created_at', 'read_at', 'payload_preview',
        'get_target_info', 'created_ago'
    )
    raw_id_fields = ('recipient', 'sender')
    list_per_page = 50
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'recipient', 'sender', 'notification_type',
                'created_at', 'created_ago'
            )
        }),
        ('Content', {
            'fields': ('message', 'is_read', 'read_at')
        }),
        ('Target Object', {
            'fields': ('target_type', 'target_id', 'get_target_info')
        }),
        ('Payload Data', {
            'fields': ('payload_preview',),
            'classes': ('collapse',)
        }),
    )
    
    def sender_preview(self, obj):
        if obj.sender:
            return obj.sender.username
        return 'System'
    sender_preview.short_description = 'From'
    
    def notification_type_formatted(self, obj):
        type_map = dict(Notification.NOTIFICATION_TYPES)
        return type_map.get(obj.notification_type, obj.notification_type)
    notification_type_formatted.short_description = 'Type'
    
    def message_preview(self, obj):
        if obj.message:
            return obj.message[:60] + ('...' if len(obj.message) > 60 else '')
        return '-'
    message_preview.short_description = 'Message'
    
    def target_preview(self, obj):
        if obj.target_type and obj.target_id:
            return f"{obj.target_type}#{obj.target_id}"
        return '-'
    target_preview.short_description = 'Target'
    
    def created_ago(self, obj):
        now = timezone.now()
        diff = now - obj.created_at
        
        if diff < timedelta(minutes=1):
            return 'Just now'
        elif diff < timedelta(hours=1):
            minutes = int(diff.total_seconds() / 60)
            return f'{minutes}m ago'
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f'{hours}h ago'
        elif diff < timedelta(days=30):
            days = diff.days
            return f'{days}d ago'
        else:
            return obj.created_at.strftime('%Y-%m-%d')
    created_ago.short_description = 'When'
    
    def payload_preview(self, obj):
        if obj.payload and isinstance(obj.payload, dict):
            # Format JSON nicely
            import json
            formatted_json = json.dumps(obj.payload, indent=2)
            return format_html('<pre style="max-height: 200px; overflow: auto;">{}</pre>', formatted_json)
        return 'Empty'
    payload_preview.short_description = 'Payload'
    
    def get_target_info(self, obj):
        if obj.target_type and obj.target_id:
            return f"Type: {obj.target_type}\nID: {obj.target_id}"
        return 'No target object'
    get_target_info.short_description = 'Target Information'
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        qs = qs.select_related('recipient', 'sender')
        return qs
    
    actions = ['mark_as_read', 'mark_as_unread', 'delete_old_notifications']
    
    def mark_as_read(self, request, queryset):
        updated = queryset.update(is_read=True, read_at=timezone.now())
        self.message_user(request, f'{updated} notification(s) marked as read.')
    mark_as_read.short_description = 'Mark selected as read'
    
    def mark_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False, read_at=None)
        self.message_user(request, f'{updated} notification(s) marked as unread.')
    mark_as_unread.short_description = 'Mark selected as unread'
    
    def delete_old_notifications(self, request, queryset):
        # Only delete notifications older than 30 days
        cutoff_date = timezone.now() - timedelta(days=30)
        old_notifications = queryset.filter(created_at__lt=cutoff_date)
        count = old_notifications.count()
        old_notifications.delete()
        self.message_user(request, f'{count} old notification(s) deleted.')
    delete_old_notifications.short_description = 'Delete notifications older than 30 days'


class NotificationPreferenceAdmin(admin.ModelAdmin):
    list_display = ('user', 'pause_all', 'email_summary', 'push_summary', 'inapp_summary', 'updated_at')
    list_filter = ('pause_all', 'created_at', 'updated_at')
    search_fields = ('user__username', 'user__email')
    readonly_fields = ('created_at', 'updated_at')
    raw_id_fields = ('user',)
    
    fieldsets = (
        ('User', {
            'fields': ('user', 'pause_all', 'created_at', 'updated_at')
        }),
        ('Email Notifications', {
            'fields': (
                'email_on_like', 'email_on_comment',
                'email_on_follow', 'email_on_mention'
            ),
            'classes': ('collapse',)
        }),
        ('Push Notifications', {
            'fields': (
                'push_on_like', 'push_on_comment',
                'push_on_follow', 'push_on_mention',
                'push_on_story_view'
            ),
            'classes': ('collapse',)
        }),
        ('In-App Notifications', {
            'fields': (
                'notify_on_like', 'notify_on_comment',
                'notify_on_follow', 'notify_on_mention',
                'notify_on_story_view'
            ),
            'classes': ('collapse',)
        }),
    )
    
    def email_summary(self, obj):
        enabled = [
            field for field in [
                'email_on_like', 'email_on_comment',
                'email_on_follow', 'email_on_mention'
            ] if getattr(obj, field)
        ]
        return f"{len(enabled)}/4 enabled"
    email_summary.short_description = 'Email'
    
    def push_summary(self, obj):
        enabled = [
            field for field in [
                'push_on_like', 'push_on_comment',
                'push_on_follow', 'push_on_mention',
                'push_on_story_view'
            ] if getattr(obj, field)
        ]
        return f"{len(enabled)}/5 enabled"
    push_summary.short_description = 'Push'
    
    def inapp_summary(self, obj):
        enabled = [
            field for field in [
                'notify_on_like', 'notify_on_comment',
                'notify_on_follow', 'notify_on_mention',
                'notify_on_story_view'
            ] if getattr(obj, field)
        ]
        return f"{len(enabled)}/5 enabled"
    inapp_summary.short_description = 'In-App'


class NotificationGroupAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'recipient', 'notification_type_formatted',
        'target_preview', 'senders_count', 'total_count',
        'is_read', 'last_updated_ago', 'created_at'
    )
    list_filter = ('notification_type', 'is_read', 'last_updated', 'created_at')
    search_fields = (
        'recipient__username', 'recipient__email',
        'notification_type', 'target_type'
    )
    readonly_fields = (
        'created_at', 'last_updated', 'senders_list',
        'get_notification_details'
    )
    raw_id_fields = ('recipient',)
    filter_horizontal = ('senders',)
    
    fieldsets = (
        ('Basic Information', {
            'fields': (
                'recipient', 'notification_type',
                'target_type', 'target_id'
            )
        }),
        ('Group Details', {
            'fields': ('count', 'is_read', 'senders_list', 'get_notification_details')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'last_updated'),
            'classes': ('collapse',)
        }),
    )
    
    def notification_type_formatted(self, obj):
        type_map = dict(Notification.NOTIFICATION_TYPES)
        return type_map.get(obj.notification_type, obj.notification_type)
    notification_type_formatted.short_description = 'Type'
    
    def target_preview(self, obj):
        if obj.target_type and obj.target_id:
            return f"{obj.target_type}#{obj.target_id}"
        return '-'
    target_preview.short_description = 'Target'
    
    def senders_count(self, obj):
        return obj.senders.count()
    senders_count.short_description = 'Senders'
    
    def total_count(self, obj):
        return obj.count
    total_count.short_description = 'Total'
    
    def last_updated_ago(self, obj):
        now = timezone.now()
        diff = now - obj.last_updated
        
        if diff < timedelta(minutes=1):
            return 'Just now'
        elif diff < timedelta(hours=1):
            minutes = int(diff.total_seconds() / 60)
            return f'{minutes}m ago'
        elif diff < timedelta(days=1):
            hours = int(diff.total_seconds() / 3600)
            return f'{hours}h ago'
        else:
            days = diff.days
            return f'{days}d ago'
    last_updated_ago.short_description = 'Last Activity'
    
    def senders_list(self, obj):
        senders = obj.senders.all()
        if senders.exists():
            return ', '.join([sender.username for sender in senders[:5]]) + \
                   (f' and {senders.count() - 5} more' if senders.count() > 5 else '')
        return 'No senders'
    senders_list.short_description = 'Senders'
    
    def get_notification_details(self, obj):
        """Get details of individual notifications in this group"""
        notifications = Notification.objects.filter(
            recipient=obj.recipient,
            notification_type=obj.notification_type,
            target_type=obj.target_type,
            target_id=obj.target_id
        )[:10]  # Show first 10
        
        if notifications.exists():
            details = []
            for notif in notifications:
                sender = notif.sender.username if notif.sender else 'System'
                time = notif.created_at.strftime('%Y-%m-%d %H:%M')
                details.append(f'• {sender} - {time}')
            
            return '\n'.join(details)
        return 'No individual notifications found'
    get_notification_details.short_description = 'Recent Notifications in Group'
    
    actions = ['mark_groups_as_read', 'mark_groups_as_unread', 'consolidate_groups']
    
    def mark_groups_as_read(self, request, queryset):
        updated = queryset.update(is_read=True)
        self.message_user(request, f'{updated} notification group(s) marked as read.')
    mark_groups_as_read.short_description = 'Mark selected groups as read'
    
    def mark_groups_as_unread(self, request, queryset):
        updated = queryset.update(is_read=False)
        self.message_user(request, f'{updated} notification group(s) marked as unread.')
    mark_groups_as_unread.short_description = 'Mark selected groups as unread'
    
    def consolidate_groups(self, request, queryset):
        """Manually trigger group consolidation for selected groups"""
        for group in queryset:
            # Update count from actual notifications
            actual_count = Notification.objects.filter(
                recipient=group.recipient,
                notification_type=group.notification_type,
                target_type=group.target_type,
                target_id=group.target_id
            ).count()
            
            if actual_count != group.count:
                group.count = actual_count
                group.save()
        
        self.message_user(request, f'{queryset.count()} group(s) consolidated.')
    consolidate_groups.short_description = 'Consolidate group counts'


# Register models
admin.site.register(Notification, NotificationAdmin)
admin.site.register(NotificationPreference, NotificationPreferenceAdmin)
admin.site.register(NotificationGroup, NotificationGroupAdmin)