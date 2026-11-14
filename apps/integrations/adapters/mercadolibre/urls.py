from django.urls import path

from . import views

app_name = "mercadolibre"
urlpatterns = [
    path("conectar/", views.ConnectView.as_view(), name="connect"),
    path("callback/", views.CallbackView.as_view(), name="callback"),
    path("pegar-url/", views.PasteReturnUrlView.as_view(), name="paste_url"),
    path("importar/<str:kind>/", views.ImportView.as_view(), name="import"),
]
