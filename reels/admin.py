from django.contrib import admin
from .models import Reel, ReelLike, ReelComment, ReelCommentLike, ReelView, SavedReel, ReelTag


@admin.register(Reel)
class ReelAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'caption_preview', 'likes_count', 'views_count', 'is_deleted', 'created_at']
    list_filter = ['is_deleted', 'created_at']
    search_fields = ['user__username', 'caption', 'audio_name']
    raw_id_fields = ['user']
    readonly_fields = ['likes_count', 'comments_count', 'views_count', 'shares_count', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        (None, {
            'fields': ('user', 'video', 'thumbnail', 'caption')
        }),
        ('Video Info', {
            'fields': ('width', 'height', 'duration')
        }),
        ('Audio', {
            'fields': ('audio_name', 'audio_url')
        }),
        ('Stats', {
            'fields': ('likes_count', 'comments_count', 'views_count', 'shares_count')
        }),
        ('Status', {
            'fields': ('is_edited', 'is_deleted')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )
    
    def caption_preview(self, obj):
        return obj.caption[:50] + '...' if len(obj.caption) > 50 else obj.caption
    caption_preview.short_description = 'Caption'


@admin.register(ReelLike)
class ReelLikeAdmin(admin.ModelAdmin):
    list_display = ['id', 'reel', 'user', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'reel__id']
    raw_id_fields = ['reel', 'user']
    ordering = ['-created_at']


@admin.register(ReelComment)
class ReelCommentAdmin(admin.ModelAdmin):
    list_display = ['id', 'reel', 'user', 'body_preview', 'parent', 'likes_count', 'created_at']
    list_filter = ['created_at', 'is_edited']
    search_fields = ['user__username', 'body', 'reel__id']
    raw_id_fields = ['reel', 'user', 'parent']
    readonly_fields = ['likes_count', 'created_at', 'updated_at']
    ordering = ['-created_at']
    
    def body_preview(self, obj):
        return obj.body[:50] + '...' if len(obj.body) > 50 else obj.body
    body_preview.short_description = 'Comment'


@admin.register(ReelCommentLike)
class ReelCommentLikeAdmin(admin.ModelAdmin):
    list_display = ['id', 'comment', 'user', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username']
    raw_id_fields = ['comment', 'user']
    ordering = ['-created_at']


@admin.register(ReelView)
class ReelViewAdmin(admin.ModelAdmin):
    list_display = ['id', 'reel', 'user', 'watch_time', 'completed', 'viewed_at']
    list_filter = ['completed', 'viewed_at']
    search_fields = ['reel__id', 'user__username']
    raw_id_fields = ['reel', 'user']
    readonly_fields = ['viewed_at']
    ordering = ['-viewed_at']


@admin.register(SavedReel)
class SavedReelAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'reel', 'folder', 'created_at']
    list_filter = ['created_at', 'folder']
    search_fields = ['user__username', 'reel__id']
    raw_id_fields = ['user', 'reel']
    ordering = ['-created_at']


@admin.register(ReelTag)
class ReelTagAdmin(admin.ModelAdmin):
    list_display = ['id', 'reel', 'tag', 'created_at']
    list_filter = ['created_at']
    search_fields = ['reel__id', 'tag__name']
    raw_id_fields = ['reel', 'tag']
    ordering = ['-created_at']