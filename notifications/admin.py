from django.contrib import admin

from notifications.models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("user", "kind", "message", "created_at", "read_at")
    list_filter = ("kind",)
    search_fields = ("message", "user__username")
