from django.urls import path

from blood_requests import views

app_name = "blood_requests"

urlpatterns = [
    path("", views.request_list, name="list"),
    path("new/", views.request_new, name="new"),
    path("mine/", views.request_mine, name="mine"),
    path("<int:pk>/", views.request_detail, name="detail"),
    path("<int:pk>/fulfil/", views.request_fulfil, name="fulfil"),
    path("<int:pk>/respond/", views.request_respond, name="respond"),
    path("<int:pk>/withdraw/", views.request_withdraw, name="withdraw"),
    path("<int:pk>/arrived/", views.request_arrived, name="arrived"),
    path("<int:pk>/report/", views.request_report, name="report"),
]
