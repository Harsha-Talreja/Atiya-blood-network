from django.urls import path

from hospitals import views

app_name = "hospitals"

urlpatterns = [
    path("dashboard/", views.dashboard, name="dashboard"),
    path("<int:pk>/verify/", views.verify, name="verify"),
]
