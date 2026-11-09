from django.contrib import admin
from django.utils import timezone

from blood_requests.models import BloodRequest, DonorResponse, Report


@admin.register(BloodRequest)
class BloodRequestAdmin(admin.ModelAdmin):
    list_display = (
        "id", "patient_name", "blood_type", "units_needed", "urgency",
        "hospital", "location", "current_status", "is_verified", "expires_at",
    )
    list_filter = ("status", "urgency", "blood_type", "is_verified", "location__city", "hospital")
    search_fields = ("patient_name", "hospital__name", "contact_phone", "requester__username")
    list_select_related = ("requester", "location", "hospital")
    raw_id_fields = ("requester", "verified_by")
    readonly_fields = ("expires_at", "created_at", "fulfilled_at", "verified_at")
    actions = ["verify_requests"]

    @admin.display(description="Status")
    def current_status(self, obj):
        return obj.display_status  # shows Expired when it applies

    @admin.action(description="Verify selected requests")
    def verify_requests(self, request, queryset):
        updated = queryset.filter(is_verified=False).update(
            is_verified=True, verified_by=request.user, verified_at=timezone.now(),
        )
        self.message_user(request, f"Verified {updated} request(s).")


@admin.register(DonorResponse)
class DonorResponseAdmin(admin.ModelAdmin):
    list_display = ("request", "donor", "created_at")
    list_filter = ("created_at",)
    search_fields = ("donor__full_name", "request__patient_name", "request__hospital__name")
    raw_id_fields = ("request", "donor")


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("request", "reason", "reporter", "resolved", "created_at")
    list_filter = ("resolved", "reason", "created_at")
    search_fields = ("request__patient_name", "reporter__username", "details")
    raw_id_fields = ("request", "reporter")
    readonly_fields = ("created_at",)
    actions = ["mark_resolved"]

    @admin.action(description="Mark selected reports as resolved")
    def mark_resolved(self, request, queryset):
        updated = queryset.update(resolved=True)
        self.message_user(request, f"Marked {updated} report(s) resolved.")
