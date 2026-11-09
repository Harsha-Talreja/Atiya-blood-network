from django.urls import path

from siteadmin import views

app_name = "siteadmin"

# Read-only pages are GET; everything that changes something is a POST route of
# its own. siteadmin.test_access walks this list and checks each entry refuses a
# non-staff user, so a route added here is covered by that test automatically.
urlpatterns = [
    path("", views.overview, name="overview"),
    path("requests/", views.requests, name="requests"),
    path("donors/", views.donors, name="donors"),
    path("users/", views.users, name="users"),
    path("reports/", views.reports, name="reports"),
    path("hospitals/", views.hospitals, name="hospitals"),
    path("audit/", views.audit, name="audit"),
    path("settings/", views.settings_page, name="settings"),
    path("notifications/", views.notifications_page, name="notifications"),
    path("requests/export.csv", views.requests_export, name="requests_export"),
    path("requests/<int:pk>/review/", views.request_review, name="request_review"),
    # Actions
    path("requests/<int:pk>/verify/", views.request_verify, name="request_verify"),
    path("requests/<int:pk>/timeout/", views.request_timeout, name="request_timeout"),
    path("requests/<int:pk>/check/", views.request_check, name="request_check"),
    path("requests/<int:pk>/remove/", views.request_remove, name="request_remove"),
    path("reports/<int:pk>/resolve/", views.report_resolve, name="report_resolve"),
    path("users/<int:pk>/block/", views.user_block, name="user_block"),
    path("users/<int:pk>/unblock/", views.user_unblock, name="user_unblock"),
    path("users/<int:pk>/delete/", views.user_delete, name="user_delete"),
]
