"""Pantallas de Depósito (M5): Preparar, Tandas, Despacho, etiquetas y expresos."""

from __future__ import annotations

from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.db.models import Count, F, Prefetch, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views import View

from apps.accounts.mixins import PanelPermissionRequiredMixin
from apps.audit import services as audit
from apps.integrations.models import Channel
from apps.sales import states
from apps.sales.models import SalesDocument, Shipment
from apps.sales.views import orders_queryset

from . import batches, dispatch, labels, pdf
from .models import Carrier, PickBatch

ORDER = SalesDocument.DocType.ORDER
CHANGE_STATUS = "sales.change_order_status"
VIEW_BATCH = "fulfillment.view_pickbatch"
PREPARE_LIMIT = 300  # pedidos que muestra Preparar
DISPATCH_LIMIT = 500  # pedidos que muestra Despacho
# Pedidos de una tanda que quedaron frenados: no avanzan solos y la tanda no se cierra.
STALLED = (states.CLAIM, states.AWAITING_CUSTOMER)


def _shown_of(qs, shown: int, limit: int) -> int | None:
    """Total de pedidos si se llegó al tope de la pantalla (para avisar que hay más); si no, None."""
    if shown < limit:
        return None
    total = qs.count()
    return total if total > shown else None


def _soon():
    return timezone.now() + timedelta(hours=2)


def _ids(request) -> list[int]:
    out = []
    for raw in request.POST.getlist("doc"):
        try:
            out.append(int(raw))
        except (TypeError, ValueError):
            continue
    return out


def _safe_next(value) -> str:
    """Solo rutas internas del panel (evita redirigir o enlazar a otro sitio)."""
    value = (value or "").strip()
    return value if value.startswith("/") and not value.startswith("//") and "\\" not in value else ""


def _file_response(content: bytes, filename: str, content_type: str, inline: bool = True) -> HttpResponse:
    response = HttpResponse(content, content_type=content_type)
    disposition = "inline" if inline else "attachment"
    response["Content-Disposition"] = f'{disposition}; filename="{filename}"'
    return response


def _labels_response(request, bundle: labels.LabelBundle, filename: str, back_url: str):
    """Archivo con las etiquetas listas; avisa cuáles faltan (el aviso se ve al volver a la pantalla)."""
    if bundle.skipped:
        messages.warning(
            request,
            f"No se imprimieron {len(bundle.skipped)}: {bundle.skipped_text()}. "
            "Las demás están en el archivo.",
        )
    if not bundle.content:
        messages.error(request, "No hay ninguna etiqueta de Mercado Libre lista para imprimir.")
        return redirect(back_url)
    labels.mark_printed(bundle.printed, user=request.user, request=request, kind=labels.KIND_ML)
    messages.success(request, f"Etiquetas de Mercado Libre generadas: {len(bundle.printed)}.")
    return _file_response(
        bundle.content,
        f"{filename}.{bundle.extension}",
        bundle.content_type,
        inline=bundle.fmt != "zpl2",
    )


# ── Preparar ─────────────────────────────────────────────────────────────


class PrepareView(PanelPermissionRequiredMixin, View):
    permission_required = CHANGE_STATUS
    template = "fulfillment/prepare.html"

    def get(self, request):
        p = request.GET
        qs = batches.preparable_orders()
        if p.get("canal"):
            qs = qs.filter(channel__code=p["canal"])
        if p.get("envio"):
            qs = qs.filter(shipments__method=p["envio"]).distinct()
        orders = list(qs.prefetch_related("lines")[:PREPARE_LIMIT])
        return render(
            request,
            self.template,
            {
                "orders": orders,
                "f": p,
                "channels": Channel.objects.filter(code__in=batches.CHANNELS),
                "methods": [
                    (m, label) for m, label in Shipment.Method.choices if m != Shipment.Method.ME_FULL
                ],
                "soon": _soon(),
                "max_batch": settings.FULFILLMENT_MAX_BATCH,
                "total": _shown_of(qs, len(orders), PREPARE_LIMIT),
            },
        )

    def post(self, request):
        try:
            batch, excluded = batches.create_batch(_ids(request), user=request.user, request=request)
        except batches.BatchError as exc:
            messages.error(request, str(exc))
            return redirect("sales:prepare")
        afuera = ""
        if excluded:
            detail = "; ".join(f"{e.ref} ({e.reason})" for e in excluded)
            afuera = f" Quedaron afuera {len(excluded)}: {detail}."
        if batch is None:
            messages.error(request, f"No se armó la tanda: ningún pedido se podía preparar.{afuera}")
            return redirect("sales:prepare")
        count = batch.items.count()
        text = f"Se armó la tanda {batch.number} con {count} pedido{'s' if count != 1 else ''}.{afuera}"
        (messages.warning if excluded else messages.success)(request, text)
        return redirect("sales:batch_detail", number=batch.number)


# ── Tandas ───────────────────────────────────────────────────────────────


class BatchListView(PanelPermissionRequiredMixin, View):
    permission_required = VIEW_BATCH

    def get(self, request):
        active = Q(items__removed_at__isnull=True, items__resolved_at__isnull=True)
        qs = (
            PickBatch.objects.select_related("created_by")
            .annotate(
                active_count=Count("items", filter=active),
                order_count=Count("items", filter=Q(items__removed_at__isnull=True)),
            )
            .order_by("-number")
        )
        week = timezone.now() - timedelta(days=7)
        return render(
            request,
            "fulfillment/batch_list.html",
            {
                "open_batches": qs.filter(status=PickBatch.Status.OPEN),
                "closed_batches": qs.filter(status=PickBatch.Status.CLOSED, closed_at__gte=week)[:50],
            },
        )


def _batch_or_404(number) -> PickBatch:
    return get_object_or_404(PickBatch.objects.select_related("created_by"), number=number)


class BatchDetailView(PanelPermissionRequiredMixin, View):
    permission_required = VIEW_BATCH

    def get(self, request, number):
        batch = _batch_or_404(number)
        orders = batches.batch_orders(batch, include_cancelled=True)
        active = [o for o in orders if o.status != states.CANCELLED]
        picking = batches.picking_list(batch, active)
        resolved_at = dict(
            batch.items.filter(removed_at__isnull=True).values_list("document_id", "resolved_at")
        )
        rows = []
        for o in orders:
            shipment = labels.label_shipment(o, o.shipments.all())
            rows.append(
                {
                    "doc": o,
                    "shipment": shipment,
                    "kind": labels.label_kind(shipment),
                    "resolved": bool(resolved_at.get(o.pk)),
                    "cancelled": o.status == states.CANCELLED,
                    "stalled": o.status in STALLED,
                }
            )
        removed = (
            batch.items.filter(removed_at__isnull=False)
            .select_related("document__channel", "removed_by")
            .order_by("removed_at")
        )
        return render(
            request,
            "fulfillment/batch_detail.html",
            {
                "batch": batch,
                "picking": picking,
                "rows": rows,
                "removed": removed,
                "has_ml": any(r["kind"] == labels.KIND_ML and not r["resolved"] for r in rows),
                "carrier_rows": [r for r in rows if r["kind"] == labels.KIND_CARRIER and not r["cancelled"]],
                "soon": _soon(),
            },
        )


class BatchPdfView(PanelPermissionRequiredMixin, View):
    permission_required = VIEW_BATCH

    def get(self, request, number):
        batch = _batch_or_404(number)
        picking = batches.picking_list(batch)
        content = pdf.checklist_pdf(batch, picking, user=request.user)
        return _file_response(content, f"tanda-{batch.number}.pdf", "application/pdf")


class BatchRemoveView(PanelPermissionRequiredMixin, View):
    permission_required = CHANGE_STATUS
    http_method_names = ["post"]

    def post(self, request, number, pk):
        batch = _batch_or_404(number)
        doc = get_object_or_404(SalesDocument, pk=pk, doc_type=ORDER)
        try:
            back = batches.remove_order(batch, doc, user=request.user, request=request)
        except batches.BatchError as exc:
            messages.error(request, str(exc))
        else:
            ref = batches.order_ref(doc)
            if back:
                messages.success(request, f"{ref} salió de la tanda y volvió a Nuevo.")
            else:
                messages.success(request, f"{ref} salió de la tanda. Sigue en «{states.label(doc.status)}».")
        return redirect("sales:batch_detail", number=batch.number)


class BatchLabelsView(PanelPermissionRequiredMixin, View):
    permission_required = CHANGE_STATUS
    http_method_names = ["post"]

    def post(self, request, number):
        batch = _batch_or_404(number)
        back = reverse("sales:batch_detail", args=[batch.number])
        orders = [o for o in batches.batch_orders(batch) if o.status not in batches.RESOLVED]
        shipments = []
        for o in orders:
            s = labels.label_shipment(o, o.shipments.all())
            if labels.label_kind(s) == labels.KIND_ML:
                s.document = o
                shipments.append(s)
        if not shipments:
            messages.error(
                request, "Esta tanda no tiene pedidos con etiqueta de Mercado Libre para imprimir."
            )
            return redirect(back)
        return _labels_response(request, labels.ml_labels(shipments), f"etiquetas-tanda-{batch.number}", back)


# ── Etiqueta de un pedido ────────────────────────────────────────────────


class OrderLabelView(PanelPermissionRequiredMixin, View):
    permission_required = CHANGE_STATUS
    http_method_names = ["post"]

    def post(self, request, pk):
        doc = get_object_or_404(SalesDocument.objects.select_related("channel"), pk=pk, doc_type=ORDER)
        back = _safe_next(request.POST.get("next")) or reverse("sales:detail", args=[pk])
        shipment = labels.label_shipment(doc)
        if labels.label_kind(shipment) != labels.KIND_ML:
            messages.error(request, "Este pedido no tiene etiqueta de Mercado Libre.")
            return redirect(back)
        shipment.document = doc
        name = f"etiqueta-{shipment.external_id or doc.number}"
        return _labels_response(request, labels.ml_labels([shipment]), name, back)


class CarrierLabelView(PanelPermissionRequiredMixin, View):
    permission_required = CHANGE_STATUS
    template = "fulfillment/carrier_label.html"

    def _context(self, doc, shipment, **extra):
        return {
            "doc": doc,
            "shipment": shipment,
            "carriers": Carrier.objects.filter(is_active=True),
            "recipient": pdf.recipient_data(doc, shipment) if shipment else None,
            "next": _safe_next(extra.pop("next", "")),
            **extra,
        }

    def _get(self, pk):
        doc = get_object_or_404(
            SalesDocument.objects.select_related("channel", "customer"), pk=pk, doc_type=ORDER
        )
        shipment = labels.label_shipment(doc)
        return doc, shipment

    def get(self, request, pk):
        doc, shipment = self._get(pk)
        context = self._context(
            doc, shipment, next=request.GET.get("next", ""), blocked=labels.carrier_label_blocked(shipment)
        )
        return render(request, self.template, context)

    def post(self, request, pk):
        doc, shipment = self._get(pk)
        blocked = labels.carrier_label_blocked(shipment)
        if blocked:
            messages.error(request, blocked)
            return redirect(_safe_next(request.POST.get("next")) or reverse("sales:detail", args=[pk]))
        carrier = request.POST.get("carrier_other", "").strip() or request.POST.get("carrier", "")
        try:
            content = labels.carrier_label(
                shipment,
                carrier=carrier,
                packages=request.POST.get("packages"),
                user=request.user,
                request=request,
            )
        except labels.LabelError as exc:
            messages.error(request, str(exc))
            return render(
                request,
                self.template,
                self._context(doc, shipment, form=request.POST, next=request.POST.get("next", "")),
                status=400,
            )
        return _file_response(content, f"rotulo-{doc.number}.pdf", "application/pdf")


# ── Despacho ─────────────────────────────────────────────────────────────

GROUPS = [
    (states.PREPARING, "En preparación", dispatch.LISTO, "Pasar a Listo"),
    (states.READY, "Listo", dispatch.DESPACHAR, "Despachar / Listo para retirar"),
    (states.READY_FOR_PICKUP, "Listo para retirar", dispatch.ENTREGAR, "Entregado (lo retiró)"),
]


class DispatchView(PanelPermissionRequiredMixin, View):
    permission_required = CHANGE_STATUS
    template = "fulfillment/dispatch.html"

    def get(self, request):
        qs = (
            orders_queryset()
            .filter(status__in=[g[0] for g in GROUPS])
            .prefetch_related("lines", Prefetch("shipments", queryset=Shipment.objects.order_by("id")))
            .order_by(F("deadline").asc(nulls_last=True), "issued_at", "id")
        )
        orders = list(qs[:DISPATCH_LIMIT])
        batch_of = dict(
            batches.active_items()
            .filter(document__in=[o.pk for o in orders])
            .values_list("document_id", "batch__number")
        )
        groups = []
        for status, title, action, button in GROUPS:
            rows = []
            for o in orders:
                if o.status != status:
                    continue
                shipment = labels.label_shipment(o, o.shipments.all())
                rows.append(
                    {
                        "doc": o,
                        "shipment": shipment,
                        "kind": labels.label_kind(shipment),
                        "pickup": any(s.method == Shipment.Method.PICKUP for s in o.shipments.all()),
                        "batch": batch_of.get(o.pk),
                    }
                )
            groups.append(
                {"status": status, "title": title, "action": action, "button": button, "rows": rows}
            )
        context = {
            "groups": groups,
            "soon": _soon(),
            "shown": len(orders),
            "total": _shown_of(qs, len(orders), DISPATCH_LIMIT),
        }
        return render(request, self.template, context)

    def post(self, request):
        action = request.POST.get("action", "")
        ids = _ids(request)
        if action == "etiquetas":
            return self._labels(request, ids)
        tracking = {}
        for key, value in request.POST.items():
            if key.startswith("tracking_") and value.strip():
                try:
                    tracking[int(key.removeprefix("tracking_"))] = value.strip()
                except ValueError:
                    continue
        try:
            result = dispatch.advance(ids, action, user=request.user, request=request, tracking=tracking)
        except dispatch.DispatchError as exc:
            messages.error(request, str(exc))
            return redirect("sales:dispatch")
        if result.done:
            by_state: dict[str, int] = {}
            for _, to in result.done:
                by_state[to] = by_state.get(to, 0) + 1
            parts = ", ".join(
                f"{n} {'pedido pasó' if n == 1 else 'pedidos pasaron'} a «{states.label(s)}»"
                for s, n in by_state.items()
            )
            tn = sum(1 for d, to in result.done if d.channel.code == "tiendanube" and to in states.TN_EFFECTS)
            extra = (
                f" {'El de Tiendanube se informa' if tn == 1 else f'Los {tn} de Tiendanube se informan'} a Tiendanube."
                if tn
                else ""
            )
            messages.success(request, f"{parts[0].upper()}{parts[1:]}.{extra}")
        if result.failed:
            hint = " Actualizá la página para ver el estado actual." if result.stale else ""
            messages.error(
                request, f"No se pudieron avanzar {len(result.failed)}: {result.failed_text()}.{hint}"
            )
        return redirect("sales:dispatch")

    def _labels(self, request, ids):
        back = reverse("sales:dispatch")
        if not ids:
            messages.error(request, "Marcá al menos un pedido para imprimir sus etiquetas.")
            return redirect(back)
        docs = (
            SalesDocument.objects.filter(pk__in=ids, doc_type=ORDER)
            .select_related("channel")
            .prefetch_related("shipments")
            .order_by("pk")
        )
        shipments, not_ml = [], []
        for d in docs:
            s = labels.label_shipment(d, d.shipments.all())
            if labels.label_kind(s) == labels.KIND_ML:
                s.document = d
                shipments.append(s)
            else:
                not_ml.append(d)
        if not shipments:
            messages.error(request, "Ninguno de los pedidos marcados tiene etiqueta de Mercado Libre.")
            return redirect(back)
        bundle = labels.ml_labels(shipments)
        bundle.skipped += [(d, "no tiene etiqueta de Mercado Libre") for d in not_ml]
        return _labels_response(request, bundle, "etiquetas-despacho", back)


# ── Expresos ─────────────────────────────────────────────────────────────


class CarrierListView(PanelPermissionRequiredMixin, View):
    permission_required = "fulfillment.manage_carriers"
    template = "fulfillment/carrier_list.html"

    def get(self, request):
        return render(request, self.template, {"carriers": Carrier.objects.all()})

    def post(self, request):
        op = request.POST.get("op", "")
        if op == "add":
            name = " ".join(request.POST.get("name", "").split())[:100]
            if not name:
                messages.error(request, "Escribí el nombre del expreso.")
            elif Carrier.objects.filter(name__iexact=name).exists():
                carrier = Carrier.objects.get(name__iexact=name)
                if not carrier.is_active:
                    carrier.is_active = True
                    carrier.save(update_fields=["is_active", "updated_at"])
                    audit.record(
                        request.user,
                        "fulfillment.carrier_changed",
                        carrier,
                        request=request,
                        accion="reactivado",
                    )
                    messages.success(request, f"«{carrier.name}» volvió a la lista.")
                else:
                    messages.info(request, f"«{carrier.name}» ya está en la lista.")
            else:
                carrier = Carrier.objects.create(name=name)
                audit.record(
                    request.user, "fulfillment.carrier_changed", carrier, request=request, accion="agregado"
                )
                messages.success(request, f"Se agregó «{name}».")
        elif op == "toggle":
            carrier = get_object_or_404(Carrier, pk=request.POST.get("id") or 0)
            carrier.is_active = not carrier.is_active
            carrier.save(update_fields=["is_active", "updated_at"])
            accion = "reactivado" if carrier.is_active else "dado de baja"
            audit.record(request.user, "fulfillment.carrier_changed", carrier, request=request, accion=accion)
            messages.success(
                request,
                f"«{carrier.name}» {'volvió a la lista' if carrier.is_active else 'ya no aparece al imprimir rótulos'}.",
            )
        else:
            messages.error(request, "Acción desconocida.")
        return redirect("sales:carriers")
