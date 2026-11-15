"""URLs del panel interno para la tienda mayorista."""

from django.urls import path

from . import panel_views as views

customer_urlpatterns = [
    path("", views.CustomerListView.as_view(), name="list"),
    path("<int:pk>/", views.CustomerDetailView.as_view(), name="detail"),
    path("<int:pk>/accion/", views.CustomerActionView.as_view(), name="action"),
]

store_admin_urlpatterns = [
    path("configuracion/", views.StoreSettingsView.as_view(), name="settings"),
    path("textos/", views.EmailTemplateListView.as_view(), name="email_templates"),
    path("textos/<slug:code>/", views.EmailTemplateEditView.as_view(), name="email_template_edit"),
    path("emails/", views.OutboundEmailListView.as_view(), name="outbound_emails"),
]
