from django.urls import path

from apps.fulfillment import views as fviews

from . import views

app_name = "sales"
urlpatterns = [
    path("", views.OrderListView.as_view(), name="list"),
    path("nuevo/", views.ManualOrderCreateView.as_view(), name="manual_create"),
    path("buscar-cliente/", views.CustomerSearchView.as_view(), name="customer_search"),
    path("buscar-producto/", views.ProductSearchView.as_view(), name="product_search"),
    path("devoluciones/", views.ReturnListView.as_view(), name="returns"),
    path("devoluciones/<int:pk>/recibir/", views.ReturnReceiveView.as_view(), name="return_receive"),
    path("devoluciones/<int:pk>/ajustado/", views.ReturnAdjustedView.as_view(), name="return_adjusted"),
    # M5 · preparación y despacho (vistas en apps/fulfillment)
    path("preparar/", fviews.PrepareView.as_view(), name="prepare"),
    path("tandas/", fviews.BatchListView.as_view(), name="batches"),
    path("tandas/<int:number>/", fviews.BatchDetailView.as_view(), name="batch_detail"),
    path("tandas/<int:number>/hoja.pdf", fviews.BatchPdfView.as_view(), name="batch_pdf"),
    path("tandas/<int:number>/etiquetas/", fviews.BatchLabelsView.as_view(), name="batch_labels"),
    path("tandas/<int:number>/sacar/<int:pk>/", fviews.BatchRemoveView.as_view(), name="batch_remove"),
    path("despacho/", fviews.DispatchView.as_view(), name="dispatch"),
    path("expresos/", fviews.CarrierListView.as_view(), name="carriers"),
    path("<int:pk>/etiqueta/", fviews.OrderLabelView.as_view(), name="order_label"),
    path("<int:pk>/rotulo/", fviews.CarrierLabelView.as_view(), name="carrier_label"),
    path("<int:pk>/", views.OrderDetailView.as_view(), name="detail"),
    path("<int:pk>/estado/", views.OrderStatusView.as_view(), name="status"),
    path("<int:pk>/manual/<str:what>/", views.ManualEditView.as_view(), name="manual_edit"),
    path("<int:pk>/devolucion/", views.ReturnCreateExpectedView.as_view(), name="return_create"),
]
