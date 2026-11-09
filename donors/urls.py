from django.urls import path

from donors import views

app_name = "donors"

urlpatterns = [
    path("me/", views.profile, name="profile"),
    path("me/edit/", views.edit, name="edit"),
    path("me/availability/", views.toggle_availability, name="toggle"),
    path("me/donated/", views.donated_today, name="donated"),
    path("search/", views.search, name="search"),
]
