"""Panel interno: acciones sobre pedidos mayoristas desde la ficha del pedido (M4) y Depósito (M5).

Confirmar pago, ver comprobantes, marcar el cobro en efectivo, marcar y resolver faltantes.
"""

from datetime import date

from django.contrib import messages
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.mixins import PanelPermissionRequiredMixin
from apps.catalog.models import Variant
from apps.fulfillment.views import _safe_next
from apps.sales.models import SalesDocument

from . import payments, shortages
from .account_views import receipt_response

ORDER = SalesDocument.DocType.ORDER


def wholesale_doc(pk) -> SalesDocument:
    return get_object_or_404(
        SalesDocument.objects.select_related("channel", "customer", "wholesale"),
        pk=pk,
        doc_type=ORDER,
        channel__code="mayorista",
    )


def _back(request, doc) -> str:
    return _safe_next(request.POST.get("next") or request.GET.get("next")) or reverse(
        "sales:detail", args=[doc.pk]
    )


def _int(raw) -> int | None:
    raw = str(raw or "").strip()
    if raw == "":
        return None
    try:
        return int(raw)
    except ValueError:
        return -1  # inválido: el servicio lo rechaza con un mensaje claro


class ConfirmPaymentView(PanelPermissionRequiredMixin, View):
    permission_required = "wholesale.confirm_payment"
    http_method_names = ["post"]

    def post(self, request, pk):
        doc = wholesale_doc(pk)
        try:
            payments.confirm_payment(doc, user=request.user, request=request)
        except payments.PaymentError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(
                request, f"Pago confirmado: {doc.channel_reference} pasó a Nuevo. Le avisamos al cliente."
            )
        return redirect("sales:detail", pk=doc.pk)


class ReceiptView(PanelPermissionRequiredMixin, View):
    permission_required = "wholesale.confirm_payment"

    def get(self, request, pk, receipt_id):
        doc = wholesale_doc(pk)
        if not payments.can_view_receipts(request.user, doc):
            raise Http404("Comprobante inexistente")
        return receipt_response(get_object_or_404(doc.receipts, pk=receipt_id))


class CashCollectedView(PanelPermissionRequiredMixin, View):
    permission_required = "sales.change_order_status"
    http_method_names = ["post"]

    def post(self, request, pk):
        doc = wholesale_doc(pk)
        try:
            payments.mark_cash_collected(doc, user=request.user, request=request)
        except payments.PaymentError as exc:
            messages.error(request, str(exc))
        else:
            messages.success(request, f"Cobro en efectivo registrado en {doc.channel_reference}.")
        return redirect(_back(request, doc))


class ShortageReportView(PanelPermissionRequiredMixin, View):
    permission_required = "wholesale.report_shortage"
    template = "wholesale/shortage_report.html"

    def get(self, request, pk):
        doc = wholesale_doc(pk)
        if not shortages.can_report(doc):
            messages.error(request, "El faltante se marca con el pedido mayorista En preparación.")
            return redirect(_back(request, doc))
        return render(
            request,
            self.template,
            {"doc": doc, "lines": doc.lines.order_by("pk"), "next": _back(request, doc)},
        )

    def post(self, request, pk):
        doc = wholesale_doc(pk)
        missing = {}
        for line in doc.lines.all():
            value = _int(request.POST.get(f"missing_{line.pk}"))
            if value:
                missing[line.pk] = value
        try:
            shortages.report(doc, missing, user=request.user, request=request)
        except shortages.ShortageError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                self.template,
                {
                    "doc": doc,
                    "lines": doc.lines.order_by("pk"),
                    "next": _back(request, doc),
                    "form": request.POST,
                },
                status=400,
            )
        messages.success(
            request,
            f"Faltante marcado: {doc.channel_reference} pasó a Esperando cliente. Le mandamos un email al cliente "
            "y avisamos a los administradores.",
        )
        return redirect(_back(request, doc))


class ShortageResolveView(PanelPermissionRequiredMixin, View):
    permission_required = "wholesale.resolve_shortage"
    template = "wholesale/shortage_resolve.html"

    def context(self, doc, form=None):
        from apps.sales import payments as sales_payments

        open_ = list(shortages.open_shortages(doc))
        missing = {s.line_id: s.missing_quantity for s in open_ if s.line_id}
        lines = list(doc.lines.order_by("pk"))
        for line in lines:
            line.missing = missing.get(line.pk, 0)
            suggested = max(0, int(line.quantity) - line.missing)
            line.value = form.get(f"qty_{line.pk}", suggested) if form is not None else suggested
        rows = list(zip(form.getlist("rep_sku"), form.getlist("rep_qty"), strict=False)) if form else []
        rows = [r for r in rows if r[0].strip()] + [("", "")] * 2
        form = form or {}
        return {
            "doc": doc,
            "lines": lines,
            "shortages": open_,
            "paid": sales_payments.is_paid(doc),
            "replacement_rows": rows,
            "difference": form.get("difference", ""),
            "refund_date": form.get("refund_date") or timezone.localdate().isoformat(),
            "refund_reference": form.get("refund_reference", ""),
        }

    def get(self, request, pk):
        doc = wholesale_doc(pk)
        if not shortages.can_resolve(doc):
            messages.error(request, "Este pedido no tiene un faltante para resolver.")
            return redirect("sales:detail", pk=doc.pk)
        return render(request, self.template, self.context(doc))

    def post(self, request, pk):
        doc = wholesale_doc(pk)
        p = request.POST
        try:
            quantities = {}
            for line in doc.lines.all():
                value = _int(p.get(f"qty_{line.pk}"))
                if value is not None:
                    quantities[line.pk] = value
            replacements = []
            for sku, qty in zip(p.getlist("rep_sku"), p.getlist("rep_qty"), strict=False):
                sku = (sku or "").strip()
                if not sku:
                    continue
                variant = Variant.objects.select_related("product").filter(sku__iexact=sku).first()
                if variant is None:
                    raise shortages.ShortageError(f"No encontramos el SKU {sku}.")
                amount = _int(qty)
                if not amount or amount < 0:
                    raise shortages.ShortageError(
                        f"Indicá cuántas unidades de {variant.sku} van en el reemplazo."
                    )
                replacements.append(shortages.Replacement(variant, amount))
            refund_date = None
            if p.get("refund_date"):
                try:
                    refund_date = date.fromisoformat(p["refund_date"])
                except ValueError as exc:
                    raise shortages.ShortageError("La fecha del reintegro no es válida.") from exc
            result = shortages.resolve(
                doc,
                quantities=quantities,
                replacements=replacements,
                difference=p.get("difference", ""),
                refund_date=refund_date,
                refund_reference=p.get("refund_reference", ""),
                user=request.user,
                request=request,
            )
        except shortages.ShortageError as exc:
            messages.error(request, str(exc))
            doc.refresh_from_db()
            return render(request, self.template, self.context(doc, form=p), status=400)
        text = f"Ajustamos {doc.channel_reference}: volvió a En preparación."
        diff = result.get("diferencia")
        if diff:
            text += (
                f" Quedó un saldo a favor de {payments.money(diff['monto'])} para su próximo pedido."
                if diff["tipo"] == "saldo a favor"
                else f" Reintegro de {payments.money(diff['monto'])} registrado."
            )
        if result.get("corregir_en_contabilium"):
            text += " Ya estaba facturado: quedó marcado «Corregir en Contabilium»."
        messages.success(request, text)
        return redirect("sales:detail", pk=doc.pk)
