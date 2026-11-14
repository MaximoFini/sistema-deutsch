from django.urls import path

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
    path("<int:pk>/", views.OrderDetailView.as_view(), name="detail"),
    path("<int:pk>/estado/", views.OrderStatusView.as_view(), name="status"),
    path("<int:pk>/manual/<str:what>/", views.ManualEditView.as_view(), name="manual_edit"),
    path("<int:pk>/devolucion/", views.ReturnCreateExpectedView.as_view(), name="return_create"),
]
