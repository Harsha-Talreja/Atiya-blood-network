from django.urls import path

from core import dev_views, views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("about/", views.about, name="about"),
    # Developer-only pages: each returns 404 unless DEBUG is on.
    path("dev/style-guide/", dev_views.style_guide, name="style_guide"),
    path("dev/403/", dev_views.preview_403, name="preview_403"),
    path("dev/404/", dev_views.preview_404, name="preview_404"),
    path("dev/500/", dev_views.preview_500, name="preview_500"),
]
