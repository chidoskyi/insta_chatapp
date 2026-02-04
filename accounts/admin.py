from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.safestring import mark_safe
from django.utils.html import format_html
from django.utils import timezone
from .models import User, Profile, EmailVerificationCode


class ProfileInline(admin.StackedInline):
    model = Profile
    can_delete = False
    verbose_name_plural = 'Profile'
    fk_name = 'user'
    fields = [
        'bio', 'avatar', 'website', 'location', 'is_private',
        'theme', 'phone', 'birthday', 'gender',
    ]


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    list_display = [
        'username',
        'email',
        'auth_provider',
        'email_verified',
        'is_active',
        'created_at',
        'pending_email_changes'
    ]
    
    list_filter = [
        'auth_provider',
        'email_verified',
        'is_active',
        'is_staff',
        'created_at'
    ]
    search_fields = ['username', 'email', 'display_name']
    ordering = ['-created_at']
    inlines = [ProfileInline]
    
    fieldsets = (
        ('Account Information', {
            'fields': ('username', 'email', 'display_name')
        }),
        ('Authentication', {
            'fields': ('password', 'auth_provider', 'email_verified', 'verified')
        }),
        ('Permissions', {
            'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at', 'last_seen')
        }),
    )
    
    add_fieldsets = (
        ('Create User', {
            'classes': ('wide',),
            'fields': ('username', 'email', 'password1', 'password2', 'auth_provider')
        }),
    )
    
    readonly_fields = ['created_at', 'last_login', 'updated_at']
    def pending_email_changes(self, obj):
        """Show count of pending email verification codes"""
        pending = EmailVerificationCode.objects.filter(
            user=obj,
            is_used=False,
            expires_at__gt=timezone.now()
        ).count()
        
        if pending > 0:
            return format_html(
                '<a href="/admin/accounts/emailverificationcode/?user__id__exact={}" '
                'style="color: #007bff; font-weight: bold;">{} pending</a>',
                obj.id,
                pending
            )
        return mark_safe('<span style="color: #6c757d;">None</span>')
    
    pending_email_changes.short_description = 'Pending Changes'
    
    def get_queryset(self, request):
        """Optimize queryset"""
        qs = super().get_queryset(request)
        return qs.prefetch_related('email_verification_codes')


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ['user', 'is_private', 'location']
    list_filter = ['is_private', 'theme', 'gender', 'created_at']
    search_fields = ['user__username', 'user__email', 'bio', 'location']
    readonly_fields = ['created_at', 'updated_at']
    ordering = ['-created_at']
    
    fieldsets = (
        ('User', {
            'fields': ('user',)
        }),
        ('Profile Info', {
            'fields': ('bio', 'avatar', 'website', 'location', 'phone')
        }),
        ('Personal', {
            'fields': ('birthday', 'gender')
        }),
        ('Settings', {
            'fields': ('is_private', 'theme')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'updated_at')
        }),
    )


@admin.register(EmailVerificationCode)
class EmailVerificationCodeAdmin(admin.ModelAdmin):
    """Admin interface for Email Verification Codes"""
    
    list_display = [
        'user_username',
        'new_email',
        'code_display',
        'status_display',
        'attempts',
        'created_at',
        'expires_at',
        'time_remaining'
    ]
    
    list_filter = [
        'is_used',
        'created_at',
        'expires_at',
    ]
    
    search_fields = [
        'user__username',
        'user__email',
        'new_email',
        'code'
    ]
    
    readonly_fields = [
        'user',
        'new_email',
        'code',
        'created_at',
        'expires_at',
        'is_used',
        'attempts',
        'status_display',
        'time_remaining',
        'is_valid_display'
    ]
    
    fieldsets = (
        ('User Information', {
            'fields': ('user', 'new_email')
        }),
        ('Verification Details', {
            'fields': ('code', 'status_display', 'is_valid_display')
        }),
        ('Usage Information', {
            'fields': ('attempts', 'is_used')
        }),
        ('Timestamps', {
            'fields': ('created_at', 'expires_at', 'time_remaining')
        }),
    )
    
    date_hierarchy = 'created_at'
    
    ordering = ['-created_at']
    
    # Custom admin actions
    actions = ['mark_as_used', 'delete_expired_codes']
    
    def user_username(self, obj):
        """Display username with link to user admin"""
        return format_html(
            '<a href="/admin/accounts/user/{}/change/">{}</a>',
            obj.user.id,
            obj.user.username
        )
    user_username.short_description = 'User'
    user_username.admin_order_field = 'user__username'
    
    def code_display(self, obj):
        """Display code with styling"""
        return format_html(
            '<span style="font-family: monospace; font-size: 16px; '
            'font-weight: bold; background: #f0f0f0; padding: 5px 10px; '
            'border-radius: 4px; letter-spacing: 2px;">{}</span>',
            obj.code
        )
    code_display.short_description = 'Code'
    
    def status_display(self, obj):
        """Display status with color coding"""
        if obj.is_used:
            color = '#6c757d'  # Gray
            status = 'Used'
            icon = '✓'
        elif timezone.now() > obj.expires_at:
            color = '#dc3545'  # Red
            status = 'Expired'
            icon = '⏱'
        elif obj.attempts >= 5:
            color = '#ffc107'  # Yellow
            status = 'Max Attempts'
            icon = '⚠'
        else:
            color = '#28a745'  # Green
            status = 'Active'
            icon = '●'
        
        return format_html(
            '<span style="color: {}; font-weight: bold;">{} {}</span>',
            color, icon, status
        )
    status_display.short_description = 'Status'
    
    def time_remaining(self, obj):
        """Display time remaining until expiration"""
        if obj.is_used:
            return format_html('<span style="color: #6c757d;">N/A (Used)</span>')
        
        now = timezone.now()
        if now > obj.expires_at:
            time_diff = now - obj.expires_at
            minutes_ago = int(time_diff.total_seconds() / 60)
            return format_html(
                '<span style="color: #dc3545;">Expired {} min ago</span>',
                minutes_ago
            )
        
        time_diff = obj.expires_at - now
        minutes_left = int(time_diff.total_seconds() / 60)
        
        if minutes_left < 5:
            color = '#dc3545'  # Red
        elif minutes_left < 10:
            color = '#ffc107'  # Yellow
        else:
            color = '#28a745'  # Green
        
        return format_html(
            '<span style="color: {};">{} min left</span>',
            color, minutes_left
        )
    time_remaining.short_description = 'Time Left'
    
    def is_valid_display(self, obj):
        """Display whether code is currently valid"""
        is_valid = obj.is_valid()
        
        if is_valid:
            return format_html(
                '<span style="color: #28a745; font-weight: bold;">✓ Valid</span>'
            )
        else:
            return format_html(
                '<span style="color: #dc3545; font-weight: bold;">✗ Invalid</span>'
            )
    is_valid_display.short_description = 'Currently Valid'
    
    def mark_as_used(self, request, queryset):
        """Mark selected codes as used"""
        updated = queryset.update(is_used=True)
        self.message_user(
            request,
            f'{updated} verification code(s) marked as used.'
        )
    mark_as_used.short_description = 'Mark selected codes as used'
    
    def delete_expired_codes(self, request, queryset):
        """Delete expired codes"""
        now = timezone.now()
        expired = queryset.filter(expires_at__lt=now)
        count = expired.count()
        expired.delete()
        self.message_user(
            request,
            f'{count} expired verification code(s) deleted.'
        )
    delete_expired_codes.short_description = 'Delete expired codes'
    
    def has_add_permission(self, request):
        """Disable manual creation of verification codes"""
        return False
    
    def get_queryset(self, request):
        """Optimize queryset with select_related"""
        qs = super().get_queryset(request)
        return qs.select_related('user')
