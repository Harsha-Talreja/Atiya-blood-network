from django.urls import path

from notifications import views

app_name = "notifications"

urlpatterns = [
    path("", views.inbox, name="inbox"),
    path("count/", views.count, name="count"),
    path("read-all/", views.read_all, name="read_all"),
    path("<int:pk>/read/", views.read, name="read"),
]
