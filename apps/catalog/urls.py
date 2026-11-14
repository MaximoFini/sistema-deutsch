from django.urls import path

from . import views

app_name = "catalog"
urlpatterns = [
    path("", views.VariantListView.as_view(), name="list"),
    path("<int:pk>/", views.VariantDetailView.as_view(), name="detail"),
    path("sin-vincular/", views.UnlinkedListView.as_view(), name="unlinked"),
    path("buscar-variantes/", views.VariantSearchView.as_view(), name="variant_search"),
    path("vincular/<int:pk>/", views.LinkView.as_view(), name="link"),
    path("contabilium/", views.ContabiliumUploadView.as_view(), name="contabilium"),
    path("contabilium/<int:pk>/", views.ContabiliumPreviewView.as_view(), name="contabilium_preview"),
    path("contabilium/<int:pk>/decidir/", views.ContabiliumDecisionView.as_view(), name="contabilium_decide"),
    path("stock-precios/", views.ChannelStockView.as_view(), name="channel_stock"),
    path("calidad/", views.QualityView.as_view(), name="quality"),
]
