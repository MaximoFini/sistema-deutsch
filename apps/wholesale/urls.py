"""URLs de la tienda (namespace `store`). Se montan en WHOLESALE_PATH o en la raíz de WHOLESALE_HOST."""

from django.urls import path

from . import account_views, views

app_name = "store"
urlpatterns = [
    path("", views.CatalogView.as_view(), name="home"),
    path("ingresar/", views.StoreLoginView.as_view(), name="login"),
    path("salir/", views.StoreLogoutView.as_view(), name="logout"),
    path("registro/", views.RegisterView.as_view(), name="register"),
    path("registro/recibido/", views.RegisterDoneView.as_view(), name="register_done"),
    path("cuenta-pendiente/", views.PendingView.as_view(), name="pending"),
    path("recuperar/", views.StorePasswordResetView.as_view(), name="password_reset"),
    path("recuperar/enviado/", views.StorePasswordResetDoneView.as_view(), name="password_reset_done"),
    path(
        "recuperar/<uidb64>/<token>/",
        views.StorePasswordResetConfirmView.as_view(),
        name="password_reset_confirm",
    ),
    path("recuperar/listo/", views.StorePasswordResetCompleteView.as_view(), name="password_reset_complete"),
    path("terminos/", views.LegalView.as_view(kind="terms"), name="terms"),
    path("privacidad/", views.LegalView.as_view(kind="privacy"), name="privacy"),
    path("estilo/", views.StyleGuideView.as_view(), name="style"),
    path("producto/<int:pk>/", views.ProductView.as_view(), name="product"),
    path("producto/<int:pk>/agregar/", views.AddToCartView.as_view(), name="add_to_cart"),
    path("carrito/", views.CartView.as_view(), name="cart"),
    path("carrito/actualizar/", views.CartUpdateView.as_view(), name="cart_update"),
    path("confirmar/", views.CheckoutView.as_view(), name="checkout"),
    path("pedidos/<int:number>/confirmado/", views.OrderDoneView.as_view(), name="order_done"),
    path("mi-cuenta/", account_views.AccountView.as_view(), name="account"),
    path("mi-cuenta/cambio/", account_views.ChangeRequestView.as_view(), name="change_request"),
    path("pedidos/<int:number>/", account_views.StoreOrderDetailView.as_view(), name="order_detail"),
    path(
        "pedidos/<int:number>/comprobante/", account_views.ReceiptUploadView.as_view(), name="receipt_upload"
    ),
    path(
        "pedidos/<int:number>/comprobantes/<int:receipt_id>/",
        account_views.ReceiptDownloadView.as_view(),
        name="receipt",
    ),
    path("pedidos/<int:number>/repetir/", account_views.RepeatOrderView.as_view(), name="repeat"),
    path("en-nombre-de/", account_views.ActingPickView.as_view(), name="acting"),
    path("en-nombre-de/terminar/", account_views.ActingStopView.as_view(), name="acting_stop"),
]
