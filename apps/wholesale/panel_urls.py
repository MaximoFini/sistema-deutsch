"""URLs del panel interno para la tienda mayorista."""

from django.urls import path

from . import order_panel_views as order_views
from . import panel_views as views

customer_urlpatterns = [
    path("", views.CustomerListView.as_view(), name="list"),
    path("invitaciones/", views.InvitationTrackingView.as_view(), name="invitations"),
    path("invitaciones/enviar/", views.InvitationSendView.as_view(), name="invitations_send"),
    path("invitaciones/<int:pk>/reenviar/", views.InvitationResendView.as_view(), name="invitation_resend"),
    path("invitaciones/<int:pk>/email/", views.InvitationEmailView.as_view(), name="invitation_email"),
    path("<int:pk>/", views.CustomerDetailView.as_view(), name="detail"),
    path("<int:pk>/accion/", views.CustomerActionView.as_view(), name="action"),
]

store_admin_urlpatterns = [
    path("configuracion/", views.StoreSettingsView.as_view(), name="settings"),
    path("textos/", views.EmailTemplateListView.as_view(), name="email_templates"),
    path("textos/<slug:code>/", views.EmailTemplateEditView.as_view(), name="email_template_edit"),
    path("emails/", views.OutboundEmailListView.as_view(), name="outbound_emails"),
]

order_urlpatterns = [
    path("<int:pk>/confirmar-pago/", order_views.ConfirmPaymentView.as_view(), name="confirm_payment"),
    path("<int:pk>/comprobantes/<int:receipt_id>/", order_views.ReceiptView.as_view(), name="receipt"),
    path("<int:pk>/cobrado/", order_views.CashCollectedView.as_view(), name="cash_collected"),
    path("<int:pk>/faltante/", order_views.ShortageReportView.as_view(), name="shortage_report"),
    path("<int:pk>/resolver-faltante/", order_views.ShortageResolveView.as_view(), name="shortage_resolve"),
]
