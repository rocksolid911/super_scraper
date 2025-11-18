"""
Authentication admin configuration.
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.contrib.auth import get_user_model
from .models import UserProfile

User = get_user_model()


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """Admin configuration for User model."""
    list_display = ['email', 'username', 'first_name', 'last_name', 'is_staff', 'is_email_verified', 'date_joined']
    list_filter = ['is_staff', 'is_superuser', 'is_active', 'is_email_verified', 'date_joined']
    search_fields = ['email', 'username', 'first_name', 'last_name']
    ordering = ['-date_joined']

    fieldsets = (
        (None, {'fields': ('email', 'username', 'password')}),
        ('Personal Info', {'fields': ('first_name', 'last_name', 'profile_image')}),
        ('Permissions', {'fields': ('is_active', 'is_staff', 'is_superuser', 'groups', 'user_permissions')}),
        ('Status', {'fields': ('is_email_verified', 'last_login', 'last_login_ip')}),
        ('Preferences', {'fields': ('preferences',)}),
    )

    add_fieldsets = (
        (None, {
            'classes': ('wide',),
            'fields': ('email', 'username', 'password1', 'password2', 'first_name', 'last_name'),
        }),
    )


@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    """Admin configuration for UserProfile model."""
    list_display = ['user', 'timezone', 'language', 'email_notifications', 'webhook_notifications', 'created_at']
    list_filter = ['email_notifications', 'webhook_notifications', 'timezone', 'language']
    search_fields = ['user__email', 'user__username', 'phone']
    readonly_fields = ['created_at', 'updated_at']
