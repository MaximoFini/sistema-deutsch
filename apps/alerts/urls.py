from django.urls import path

from . import views

app_name = "alerts"
urlpatterns = [
    path("", views.AlertListView.as_view(), name="list"),
    path("campana/", views.AlertBellView.as_view(), name="bell"),
    path("leidas/", views.AlertMarkReadView.as_view(), name="mark_all_read"),
    path("<int:pk>/leida/", views.AlertMarkReadView.as_view(), name="mark_read"),
]
