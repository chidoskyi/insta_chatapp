from django.contrib import admin
from django.utils import timezone
from .models import Story, StoryView, StoryHighlight, HighlightStory, HighlightPost


@admin.register(Story)
class StoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'media_type', 'viewers_count', 'is_expired_display', 'created_at', 'expires_at']
    list_filter = ['media_type', 'created_at', 'expires_at']
    search_fields = ['user__username', 'caption']
    raw_id_fields = ['user']
    readonly_fields = ['viewers_count', 'created_at', 'is_expired_display', 'time_remaining_display']
    ordering = ['-created_at']
    
    fieldsets = (
        (None, {
            'fields': ('user', 'media_type', 'media', 'thumbnail', 'caption')
        }),
        ('Media Info', {
            'fields': ('width', 'height', 'duration')
        }),
        ('Stats', {
            'fields': ('viewers_count', 'is_expired_display', 'time_remaining_display')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'expires_at')
        }),
    )
    
    def is_expired_display(self, obj):
        return obj.is_expired
    is_expired_display.short_description = 'Expired'
    is_expired_display.boolean = True
    
    def time_remaining_display(self, obj):
        if obj.is_expired:
            return "Expired"
        seconds = obj.time_remaining
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"
    time_remaining_display.short_description = 'Time Remaining'


@admin.register(StoryView)
class StoryViewAdmin(admin.ModelAdmin):
    list_display = ['id', 'story', 'viewer', 'viewed_at']
    list_filter = ['viewed_at']
    search_fields = ['story__id', 'viewer__username', 'story__user__username']
    raw_id_fields = ['story', 'viewer']
    ordering = ['-viewed_at']
    
    def has_add_permission(self, request):
        return False


class HighlightStoryInline(admin.TabularInline):
    model = HighlightStory
    extra = 0
    raw_id_fields = ['story']
    fields = ['story', 'order']


class HighlightPostInline(admin.TabularInline):
    model = HighlightPost
    extra = 0
    raw_id_fields = ['post']
    fields = ['post', 'order']


# @admin.register(StoryHighlight)
# class StoryHighlightAdmin(admin.ModelAdmin):
#     list_display = ['id', 'user', 'title', 'items_count', 'created_at']
#     list_filter = ['created_at']
#     search_fields = ['user__username', 'title']
#     raw_id_fields = ['user']
#     readonly_fields = ['created_at', 'updated_at', 'items_count']
#     inlines = [HighlightStoryInline, HighlightPostInline]
#     ordering = ['-created_at']
    
#     def items_count(self, obj):
#         return obj.stories.count() + obj.posts.count()
#     items_count.short_description = 'Total Items'


@admin.register(HighlightStory)
class HighlightStoryAdmin(admin.ModelAdmin):
    list_display = ['id', 'highlight', 'story', 'order', 'added_at']
    list_filter = ['added_at']
    search_fields = ['highlight__title', 'story__id']
    raw_id_fields = ['highlight', 'story']
    ordering = ['highlight', 'order']


@admin.register(HighlightPost)
class HighlightPostAdmin(admin.ModelAdmin):
    list_display = ['id', 'highlight', 'post', 'order', 'added_at']
    list_filter = ['added_at']
    search_fields = ['highlight__title', 'post__id']
    raw_id_fields = ['highlight', 'post']
    ordering = ['highlight', 'order']


@admin.register(StoryHighlight)
class StoryHighlightAdmin(admin.ModelAdmin):
    list_display = ['id', 'user', 'title', 'stories_count', 'created_at']
    list_filter = ['created_at']
    search_fields = ['user__username', 'title']
    raw_id_fields = ['user']
    readonly_fields = ['created_at', 'updated_at', 'stories_count']
    inlines = [HighlightStoryInline]
    ordering = ['-created_at']
    
    def stories_count(self, obj):
        return obj.stories.count()
    stories_count.short_description = 'Stories Count'
