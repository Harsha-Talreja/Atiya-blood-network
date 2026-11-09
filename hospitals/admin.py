from django.contrib import admin

from hospitals.models import Hospital, HospitalAccount


@admin.register(Hospital)
class HospitalAdmin(admin.ModelAdmin):
    list_display = ("name", "location")
    list_filter = ("location__city",)
    search_fields = ("name",)
    list_select_related = ("location",)


@admin.register(HospitalAccount)
class HospitalAccountAdmin(admin.ModelAdmin):
    list_display = ("staff_name", "hospital", "user")
    list_filter = ("hospital__location__city",)
    search_fields = ("staff_name", "hospital__name", "user__username")
    raw_id_fields = ("user",)
    list_select_related = ("hospital", "user")
