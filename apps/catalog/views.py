from django import forms
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Exists, OuterRef, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect
from django.utils import timezone
from django.views import View
from django.views.generic import DetailView, ListView, TemplateView

from apps.accounts.mixins import PanelPermissionRequiredMixin
from apps.integrations.models import Channel, ExternalRef
from apps.pricing import services as pricing
from apps.pricing.models import PriceList

from . import channel_view, contabilium_import, linking, quality
from .models import ContabiliumImport, ListingVariation, Variant

XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _search(qs, q: str):
    q = (q or "").strip()
    if not q:
        return qs
    return qs.filter(Q(sku__icontains=q) | Q(barcode__icontains=q) | Q(product__name__icontains=q))


def _paginate(request, items, per_page):
    return Paginator(items, per_page).get_page(request.GET.get("page"))


def _querystring(request) -> str:
    """Filtros actuales sin `page` ni `formato`, para los links de página."""
    query = request.GET.copy()
    query.pop("page", None)
    query.pop("formato", None)
    return query.urlencode()


def _xlsx_response(content: bytes, name: str) -> HttpResponse:
    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{name}-{timezone.localdate():%Y%m%d}.xlsx"'
    return response


# ── Lista y ficha ─────────────────────────────────────────────────────────


class VariantListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "catalog.view_variant"
    template_name = "catalog/list.html"
    paginate_by = 50
    context_object_name = "variants"

    def get_queryset(self):
        qs = Variant.objects.select_related("product").order_by("product__name", "sku")
        filtro = self.request.GET.get("filtro", "")
        if filtro != "inactivas":
            qs = qs.filter(is_active=True)
        else:
            qs = qs.filter(is_active=False)
        linked = ListingVariation.objects.filter(variant=OuterRef("pk"))
        if filtro == "sin_ml":
            qs = qs.exclude(Exists(linked.filter(listing__channel__code="mercadolibre")))
        elif filtro == "sin_contabilium":
            qs = qs.exclude(Exists(linked.filter(listing__channel__code="contabilium")))
        elif filtro == "revisar":
            qs = qs.filter(needs_review=True)
        return _search(qs, self.request.GET.get("q"))

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["q"] = self.request.GET.get("q", "")
        ctx["filtro"] = self.request.GET.get("filtro", "")
        query = self.request.GET.copy()
        query.pop("page", None)
        ctx["querystring"] = query.urlencode()
        return ctx


class VariantDetailView(PanelPermissionRequiredMixin, DetailView):
    permission_required = "catalog.view_variant"
    template_name = "catalog/detail.html"
    model = Variant
    context_object_name = "variant"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        v = self.object
        ctx["tn_ref"] = ExternalRef.objects.filter(
            channel__code="tiendanube", content_type__model="variant", object_id=v.pk
        ).first()
        rows = (
            ListingVariation.objects.filter(variant=v)
            .select_related("listing__channel")
            .order_by("listing__channel__code")
        )
        ctx["ml_rows"] = [r for r in rows if r.listing.channel.code == "mercadolibre"]
        ctx["cb_rows"] = [r for r in rows if r.listing.channel.code == "contabilium"]
        ctx["price_minorista"] = pricing.current_price(PriceList.objects.get(code="MINORISTA"), v)
        ctx["price_mayorista"] = pricing.current_price(PriceList.objects.get(code="MAYORISTA"), v)
        ctx["stock_level"] = v.stock_levels.filter(warehouse__is_default=True).first()
        return ctx


# ── Sin vincular y vincular a mano ────────────────────────────────────────


class UnlinkedListView(PanelPermissionRequiredMixin, ListView):
    permission_required = "catalog.manage_links"
    template_name = "catalog/unlinked.html"
    paginate_by = 50
    context_object_name = "rows"

    def get_queryset(self):
        qs = (
            ListingVariation.objects.filter(variant__isnull=True)
            .exclude(listing__status__in=["closed", "missing"])
            .select_related("listing__channel")
            .order_by("listing__channel__code", "listing__title")
        )
        channel = self.request.GET.get("canal")
        if channel:
            qs = qs.filter(listing__channel__code=channel)
        return qs

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["canal"] = self.request.GET.get("canal", "")
        ctx["channels"] = Channel.objects.filter(code__in=["mercadolibre", "contabilium"])
        return ctx


class VariantSearchView(PanelPermissionRequiredMixin, TemplateView):
    """Fragmento HTMX: hasta 10 variantes para elegir al vincular."""

    permission_required = "catalog.manage_links"
    template_name = "catalog/_variant_search.html"

    def get_context_data(self, **kwargs):
        q = self.request.GET.get("q", "")
        results = _search(Variant.objects.select_related("product"), q)[:10] if len(q.strip()) >= 2 else []
        return {"results": results, "row_id": self.request.GET.get("row")}


class LinkView(PanelPermissionRequiredMixin, View):
    permission_required = "catalog.manage_links"
    http_method_names = ["post"]

    def post(self, request, pk):
        row = get_object_or_404(ListingVariation.objects.select_related("listing__channel", "variant"), pk=pk)
        back = request.POST.get("next") or "catalog:unlinked"
        if request.POST.get("action") == "unlink":
            linking.unlink_manual(row, user=request.user, request=request)
            messages.success(
                request, f"Desvinculado {row.listing.external_id}. No se va a volver a vincular solo."
            )
            return redirect(back)
        variant = get_object_or_404(Variant, pk=request.POST.get("variant"))
        if row.variant_id and row.variant_id != variant.pk and request.POST.get("confirm") != "1":
            messages.error(
                request,
                f"{row.listing.external_id} ya está vinculado al SKU {row.variant.sku}. "
                "Confirmá el reemplazo para continuar.",
            )
            return redirect(back)
        linking.link_manual(row, variant, user=request.user, request=request)
        messages.success(request, f"{row.listing.external_id} vinculado al SKU {variant.sku}.")
        return redirect(back)


# ── Importación de Contabilium ────────────────────────────────────────────


class UploadForm(forms.Form):
    archivo = forms.FileField(label="Archivo de productos de Contabilium (.xlsx o .csv)")


class ContabiliumUploadView(PanelPermissionRequiredMixin, View):
    permission_required = "catalog.import_contabilium"

    def get(self, request):
        from django.shortcuts import render

        return render(
            request,
            "catalog/contabilium_upload.html",
            {
                "form": UploadForm(),
                "imports": ContabiliumImport.objects.select_related("uploaded_by")[:20],
            },
        )

    def post(self, request):
        form = UploadForm(request.POST, request.FILES)
        if not form.is_valid():
            messages.error(request, "Elegí un archivo.")
            return redirect("catalog:contabilium")
        upload = form.cleaned_data["archivo"]
        try:
            imp = contabilium_import.create_preview(
                filename=upload.name, content=upload.read(), user=request.user
            )
        except contabilium_import.ImportFileError as exc:
            messages.error(request, str(exc))
            return redirect("catalog:contabilium")
        return redirect("catalog:contabilium_preview", pk=imp.pk)


class ContabiliumPreviewView(PanelPermissionRequiredMixin, DetailView):
    permission_required = "catalog.import_contabilium"
    template_name = "catalog/contabilium_preview.html"
    model = ContabiliumImport
    context_object_name = "imp"


class ContabiliumDecisionView(PanelPermissionRequiredMixin, View):
    permission_required = "catalog.import_contabilium"
    http_method_names = ["post"]

    def post(self, request, pk):
        imp = get_object_or_404(ContabiliumImport, pk=pk)
        if request.POST.get("action") == "discard":
            contabilium_import.discard(imp)
            messages.success(request, "Importación descartada. No se aplicó nada.")
            return redirect("catalog:contabilium")
        try:
            stats = contabilium_import.apply_import(imp, user=request.user, request=request)
            from apps.core.db import refresh_statistics

            refresh_statistics()  # carga grande: estadísticas al día
        except contabilium_import.ImportNotApplicable as exc:
            messages.error(request, str(exc))
            return redirect("catalog:contabilium_preview", pk=pk)
        messages.success(
            request,
            f"Importación aplicada: {stats['linked']} vinculados, {stats['unlinked']} sin vincular, "
            f"{stats['wholesale_updated']} precios mayoristas actualizados, {stats['missing']} códigos que ya no vienen.",
        )
        return redirect("catalog:contabilium_preview", pk=pk)


# ── Vistas de control ─────────────────────────────────────────────────────


class ChannelStockView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "catalog.view_channel_stock"
    template_name = "catalog/channel_stock.html"
    paginate_by = 100

    def variants(self):
        return _search(
            Variant.objects.filter(is_active=True).order_by("product__name", "sku"), self.request.GET.get("q")
        )

    def rows(self):
        rows = channel_view.build_rows(self.variants())
        if self.request.GET.get("diferencias"):
            rows = [r for r in rows if r.has_diff]
        return rows

    def get(self, request, *args, **kwargs):
        if request.GET.get("formato") == "xlsx":  # el Excel exporta todo, sin paginar
            return _xlsx_response(channel_view.export_xlsx(self.rows()), "stock-precios")
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        # El conteo de diferencias necesita todas las filas (se calculan en memoria, pocas consultas);
        # lo pesado era dibujar miles de filas: se muestran de a 100.
        rows = self.rows()
        diff_count = len(rows) if self.request.GET.get("diferencias") else sum(1 for r in rows if r.has_diff)
        page = _paginate(self.request, rows, self.paginate_by)
        return {
            "rows": page.object_list,
            "page_obj": page,
            "paginator": page.paginator,
            "is_paginated": page.paginator.num_pages > 1,
            "querystring": _querystring(self.request),
            "q": self.request.GET.get("q", ""),
            "diferencias": self.request.GET.get("diferencias", ""),
            "diff_count": diff_count,
        }


class QualityView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "catalog.view_quality"
    template_name = "catalog/quality.html"
    paginate_by = 100

    def issues(self):
        items = quality.find_issues()
        code = self.request.GET.get("tipo")
        severity = self.request.GET.get("severidad")
        filtered = [
            i for i in items if (not code or i.code == code) and (not severity or i.severity == severity)
        ]
        return items, filtered

    def get(self, request, *args, **kwargs):
        if request.GET.get("formato") == "xlsx":
            _, filtered = self.issues()
            return _xlsx_response(
                quality.export_xlsx(filtered, request.build_absolute_uri("/")[:-1]), "calidad-catalogo"
            )
        return super().get(request, *args, **kwargs)

    def get_context_data(self, **kwargs):
        items, filtered = self.issues()
        counts = {}
        for i in items:
            counts.setdefault(i.code, {"label": i.title, "severity": i.severity, "count": 0})["count"] += 1
        page = _paginate(self.request, filtered, self.paginate_by)
        return {
            "issues": page.object_list,
            "page_obj": page,
            "paginator": page.paginator,
            "is_paginated": page.paginator.num_pages > 1,
            "querystring": _querystring(self.request),
            "counts": counts,
            "total": len(items),
            "critical": sum(1 for i in items if i.severity == quality.CRITICAL),
            "tipo": self.request.GET.get("tipo", ""),
            "severidad": self.request.GET.get("severidad", ""),
        }
