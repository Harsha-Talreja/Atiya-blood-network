from django.contrib import admin

from core.models import Location


@admin.register(Location)
class LocationAdmin(admin.ModelAdmin):
    list_display = ("city", "area")
    list_filter = ("city",)
    search_fields = ("city", "area")
