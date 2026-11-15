from django.urls import path

from . import views

app_name = "reports"
urlpatterns = [
    path("", views.SummaryView.as_view(), name="summary"),
    path("excel/", views.SummaryView.as_view(excel=True), name="summary_excel"),
    path("ventas/", views.SalesView.as_view(), name="sales"),
    path("ventas/excel/", views.SalesView.as_view(excel=True), name="sales_excel"),
    path("productos/", views.ProductsView.as_view(), name="products"),
    path("productos/excel/", views.ProductsView.as_view(excel=True), name="products_excel"),
    path("operacion/", views.OperationsView.as_view(), name="operations"),
    path("operacion/excel/", views.OperationsView.as_view(excel=True), name="operations_excel"),
]
