from django.contrib import admin

from donors.models import DonorProfile


@admin.register(DonorProfile)
class DonorProfileAdmin(admin.ModelAdmin):
    list_display = (
        "full_name", "blood_type", "location", "phone",
        "is_available", "last_donation_date", "eligible", "phone_consent",
    )
    list_filter = ("blood_type", "is_available", "phone_consent", "location__city")
    search_fields = ("full_name", "phone", "user__username", "user__email")
    list_select_related = ("user", "location")
    raw_id_fields = ("user",)
    readonly_fields = ("created_at",)

    @admin.display(boolean=True, description="Eligible")
    def eligible(self, obj):
        return obj.is_eligible
