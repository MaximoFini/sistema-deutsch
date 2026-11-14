from django.urls import path

from . import views

app_name = "integrations"
urlpatterns = [
    path("", views.IntegrationStatusView.as_view(), name="status"),
    path("<slug:channel_code>/reprocesar/", views.RetryFailedEventsView.as_view(), name="retry_failed"),
    path(
        "<slug:channel_code>/escritura/<str:kind>/",
        views.ToggleWriteSwitchView.as_view(),
        name="toggle_write_switch",
    ),
]

webhook_urlpatterns = [
    path("<slug:channel_code>/", views.WebhookView.as_view(), name="webhook"),
]
