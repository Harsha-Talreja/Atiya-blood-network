from django.contrib import admin

from accounts.models import RetiredCnic


@admin.register(RetiredCnic)
class RetiredCnicAdmin(admin.ModelAdmin):
    """Fingerprints of CNICs whose account was deleted. Delete a row to let that CNIC be used again."""

    list_display = ("__str__", "retired_at")
    readonly_fields = ("cnic_hash", "retired_at")
