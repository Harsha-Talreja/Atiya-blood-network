from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    # Django's own admin, for rare and risky edits.
    path("i18n/", include("django.conf.urls.i18n")),   # the language switcher posts here
    path("admin/", admin.site.urls),
    # The project's own panel, for the daily work. Staff only; see
    # siteadmin.decorators.staff_only.
    path("admin-panel/", include("siteadmin.urls")),
    path("", include("core.urls")),
    path("accounts/", include("accounts.urls")),
    path("donors/", include("donors.urls")),
    path("requests/", include("blood_requests.urls")),
    path("hospitals/", include("hospitals.urls")),
    path("notifications/", include("notifications.urls")),
]
