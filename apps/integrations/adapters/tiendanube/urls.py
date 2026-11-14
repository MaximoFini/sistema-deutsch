from django.urls import path

from . import views

app_name = "tiendanube"
urlpatterns = [
    path("conectar/", views.ConnectView.as_view(), name="connect"),
    path("callback/", views.CallbackView.as_view(), name="callback"),
    path("importar/<str:kind>/", views.ImportView.as_view(), name="import"),
]

privacy_urlpatterns = [
    path("<str:kind>/", views.PrivacyWebhookView.as_view(), name="privacy"),
]
