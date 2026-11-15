"""Pantallas de reportes (M7). Solo lectura y solo para quien tiene `reports.view_reports`."""

from django.core.paginator import Paginator
from django.views.generic import TemplateView

from apps.accounts.mixins import PanelPermissionRequiredMixin

from . import excel, filters, queries
from .excel import Sheet
from .templatetags.reports import money

TABS = [
    ("reports:summary", "Resumen"),
    ("reports:sales", "Ventas"),
    ("reports:products", "Productos"),
    ("reports:operations", "Operación"),
    ("reports:wholesale", "Mayorista"),
]
SALES_COLUMNS = [
    ("unidades", "Unidades"),
    ("pedidos", "Pedidos"),
    ("bruto", "Bruto"),
    ("neto", "Neto"),
    ("precio", "Precio prom. por unidad"),
]


def _num(value):
    """Cantidades enteras como int en el Excel (3 en vez de 3.000)."""
    if value is None:
        return None
    return int(value) if value == int(value) else float(value)


def net_footer(table: dict) -> str:
    """Aclaración debajo del total cuando se agrupa por producto, variante, talle o color (vacía si no)."""
    t = table["totals"]
    if "neto_resumen" not in t:
        return ""
    return (
        f"Neto sin descontar envíos de Mercado Libre ({money(t['envio'])}). "
        f"El neto del resumen, con envíos, es {money(t['neto_resumen'])}."
    )


class ReportView(PanelPermissionRequiredMixin, TemplateView):
    permission_required = "reports.view_reports"
    tab = ""
    excel = False  # las URLs …/excel/ usan la misma vista con excel=True
    excel_name = "reporte"
    extra_params: tuple[str, ...] = ()  # parámetros propios de la pestaña que se conservan en los links

    def get(self, request, *args, **kwargs):
        self.f = filters.from_request(request.GET)
        if self.excel:
            return excel.response(self.sheets(), self.excel_name)
        return super().get(request, *args, **kwargs)

    def sheets(self) -> list[Sheet]:  # pragma: no cover - cada pestaña lo define
        raise NotImplementedError

    def note(self) -> str:
        return f"Período: {self.f.label} · {self.f.channel_label}. Montos informados por cada canal."

    def params(self) -> dict:
        data = self.f.params()
        for name in self.extra_params:
            value = self.request.GET.get(name)
            if value:
                data[name] = value
        return data

    def get_context_data(self, **kwargs):
        from urllib.parse import urlencode

        params = self.params()
        return {
            "f": self.f,
            "presets": filters.PRESETS,
            "channels": filters.CHANNELS,
            "tabs": TABS,
            "tab": self.tab,
            "filter_qs": self.f.querystring(),
            "querystring": urlencode(params),
            "extra_hidden": {k: v for k, v in params.items() if k in self.extra_params},
            "excel_url_name": f"{self.request.resolver_match.view_name}_excel"
            if self.request.resolver_match
            else "",
            **kwargs,
        }


class SummaryView(ReportView):
    template_name = "reports/summary.html"
    tab = "reports:summary"
    excel_name = "reporte-resumen"

    def get_context_data(self, **kwargs):
        by_day = queries.sales_by_day(self.f)
        return super().get_context_data(
            kpis=queries.kpis(self.f),
            by_day=by_day,
            share=queries.channel_share(self.f, by_day),
            heat=queries.heatmap(self.f),
            hours=range(24),
            chart_data={
                "labels": by_day["labels"],
                "series": [
                    {"name": s["name"], "color": s["color"], "values": s["values"]} for s in by_day["series"]
                ],
                "share": [
                    {"name": s["name"], "color": s["color"], "total": float(s["total"])}
                    for s in by_day["series"]
                ],
            },
            **kwargs,
        )

    def sheets(self):
        k = queries.kpis(self.f)
        by_day = queries.sales_by_day(self.f)
        heat = queries.heatmap(self.f)
        prev = k["previous"]
        kpi_rows = [
            [
                i["label"],
                i["value"] if i["kind"] == "money" else _num(i["value"]),
                i["previous"] if i["kind"] == "money" else _num(i["previous"]),
                i["change"],
            ]
            for i in k["items"]
        ]
        kpi_rows.append(["Ventas de ML con neto pendiente", k["net_pending"], None, None])
        names = [s["name"] for s in by_day["series"]]
        day_rows = [
            [
                label,
                *[s["values"][i] for s in by_day["series"]],
                sum(s["values"][i] for s in by_day["series"]),
            ]
            for i, label in enumerate(by_day["labels"])
        ]
        return [
            Sheet(
                "Indicadores",
                ["Indicador", "Período", f"Período anterior ({prev.label})", "Variación %"],
                kpi_rows,
                money_columns={1, 2},
                note=self.note() + " Tiendanube y manuales: sin comisiones del canal (neto = bruto).",
            ),
            Sheet(
                "Ventas por " + {"day": "día", "week": "semana", "month": "mes"}[by_day["bucket"]],
                ["Fecha", *names, "Total"],
                day_rows,
                money_columns=set(range(1, len(names) + 2)),
                note=self.note(),
            ),
            Sheet(
                "Días y horas",
                ["Día", *[f"{h:02d} h" for h in range(24)], "Total"],
                [[r["day"], *[c["count"] for c in r["cells"]], r["total"]] for r in heat["rows"]],
                note=self.note(),
            ),
        ]


class SalesView(ReportView):
    template_name = "reports/sales.html"
    tab = "reports:sales"
    excel_name = "reporte-ventas"
    extra_params = ("agrupar", "orden")
    paginate_by = 100

    def table(self):
        group_by = self.request.GET.get("agrupar", "canal")
        table = queries.sales_table(self.f, group_by, self.request.GET.get("orden") or None)
        return queries.add_net_summary(self.f, table)

    def get_context_data(self, **kwargs):
        from urllib.parse import urlencode

        table = self.table()
        page = Paginator(table["rows"], self.paginate_by).get_page(self.request.GET.get("page"))
        base = {**self.f.params(), "agrupar": table["group_by"]}
        order = table["order"]
        headers = []
        for field, label in [("clave", queries.GROUPS[table["group_by"]]), *SALES_COLUMNS]:
            current = order.lstrip("-") == field
            desc = order.startswith("-")
            # Primer clic: texto de A a Z y números de mayor a menor; el segundo invierte.
            next_order = (
                ("" if desc else "-") + field if current else (field if field == "clave" else f"-{field}")
            )
            headers.append(
                {
                    "field": field,
                    "label": label,
                    "url": "?" + urlencode({**base, "orden": next_order}),
                    "arrow": ("▼" if desc else "▲") if current else "",
                }
            )
        return super().get_context_data(
            table=table,
            rows=page.object_list,
            page_obj=page,
            paginator=page.paginator,
            is_paginated=page.paginator.num_pages > 1,
            headers=headers,
            group_links=[
                {"key": key, "label": label, "url": "?" + urlencode({**self.f.params(), "agrupar": key})}
                for key, label in queries.GROUPS.items()
            ],
            variant_cols=table["group_by"] == "variante",
            net_footer=net_footer(table),
            **kwargs,
        )

    def sheets(self):
        table = self.table()
        variant = table["group_by"] == "variante"
        extra = ["Producto", "Talle", "Color"] if variant else []
        headers = [queries.GROUPS[table["group_by"]], *extra, *[label for _, label in SALES_COLUMNS]]

        def values(r):
            ext = [r.get("producto", ""), r.get("talle", ""), r.get("color", "")] if variant else []
            return [r["clave"], *ext, _num(r["unidades"]), r["pedidos"], r["bruto"], r["neto"], r["precio"]]

        t = table["totals"]
        offset = len(extra)
        return [
            Sheet(
                "Ventas",
                headers,
                [values(r) for r in table["rows"]],
                totals=[
                    "Total",
                    *[""] * offset,
                    _num(t["unidades"]),
                    t["pedidos"],
                    t["bruto"],
                    t["neto"],
                    t["precio"],
                ],
                money_columns={offset + 3, offset + 4, offset + 5},
                note=self.note()
                + (
                    ""
                    if table["group_by"] in queries.DOC_GROUPS
                    else " Por producto se suma lo cobrado por el producto (sin envío). " + net_footer(table)
                ),
            )
        ]


class ProductsView(ReportView):
    template_name = "reports/products.html"
    tab = "reports:products"
    excel_name = "reporte-productos"
    extra_params = ("por", "veces")

    def min_times(self) -> int:
        from django.conf import settings

        try:
            return max(1, min(99, int(self.request.GET.get("veces") or settings.REPORTS_STOCKOUT_MIN_TIMES)))
        except ValueError:
            return settings.REPORTS_STOCKOUT_MIN_TIMES

    def by(self) -> str:
        return "bruto" if self.request.GET.get("por") == "bruto" else "unidades"

    def get_context_data(self, **kwargs):
        from urllib.parse import urlencode

        base = {**self.f.params(), "veces": self.min_times()}
        out = queries.stockouts(self.f, self.min_times())
        return super().get_context_data(
            top=queries.top_products(self.f, self.by()),
            out=out,
            history_late=out["history_since"] is not None and out["history_since"] > self.f.start,
            by_urls={
                "unidades": "?" + urlencode({**base, "por": "unidades"}),
                "bruto": "?" + urlencode({**base, "por": "bruto"}),
            },
            min_times=self.min_times(),
            **kwargs,
        )

    def sheets(self):
        top = queries.top_products(self.f, self.by())
        out = queries.stockouts(self.f, self.min_times())
        metric = "bruto" if top["by"] == "bruto" else "unidades"
        cols = ["Unidades", "Bruto", "Stock disponible"]
        return [
            Sheet(
                "Productos más vendidos",
                ["Producto", *cols],
                [[r["clave"], _num(r["unidades"]), r["bruto"], _num(r["stock"])] for r in top["products"]],
                money_columns={2},
                note=self.note() + f" Top 50 por {metric}.",
            ),
            Sheet(
                "Variantes más vendidas",
                ["SKU", "Producto", "Talle", "Color", *cols],
                [
                    [
                        r["clave"],
                        r.get("producto", ""),
                        r.get("talle", ""),
                        r.get("color", ""),
                        _num(r["unidades"]),
                        r["bruto"],
                        _num(r["stock"]),
                    ]
                    for r in top["variants"]
                ],
                money_columns={5},
                note=self.note() + f" Top 50 por {metric}.",
            ),
            Sheet(
                "Se agotan seguido",
                [
                    "SKU",
                    "Producto",
                    "Talle / color",
                    "Veces sin stock",
                    "Días sin stock",
                    "Vendidas",
                    "Stock disponible",
                ],
                [
                    [
                        r["sku"],
                        r["producto"],
                        r["atributos"],
                        r["veces"],
                        r["dias_sin_stock"],
                        _num(r["vendidas"]),
                        _num(r["stock"]),
                    ]
                    for r in out["rows"]
                ],
                note=self.note() + f" Variantes que quedaron en 0 al menos {out['min_times']} veces.",
            ),
        ]


class OperationsView(ReportView):
    template_name = "reports/operations.html"
    tab = "reports:operations"
    excel_name = "reporte-operacion"

    def data(self):
        return {
            "responses": queries.response_times(self.f),
            "dispatch": queries.dispatch_times(self.f),
            "flex": queries.flex_on_time(self.f),
            "manual": queries.manual_pending(),
        }

    def get_context_data(self, **kwargs):
        data = self.data()
        data["flex_late"] = data["flex"]["late"][:100]
        return super().get_context_data(heat=queries.heatmap(self.f), hours=range(24), **data, **kwargs)

    def sheets(self):
        d = self.data()
        resp = d["responses"]
        time_headers = ["Cantidad", "Mediana (h)", "Percentil 90 (h)"]
        resp_rows = []
        if resp["available"]:
            o = resp["overall"]
            resp_rows.append(["Todas", o["n"], o["mediana_h"], o["p90_h"], o["pct_1h"], o["pct_12h"]])
            resp_rows += [
                [p["persona"], p["n"], p["mediana_h"], p["p90_h"], p["pct_1h"], p["pct_12h"]]
                for p in resp["people"]
            ]
        disp = d["dispatch"]
        disp_rows = [
            ["Todos", "", disp["overall"]["n"], disp["overall"]["mediana_h"], disp["overall"]["p90_h"]]
        ]
        disp_rows += [["Canal", r["clave"], r["n"], r["mediana_h"], r["p90_h"]] for r in disp["by_channel"]]
        disp_rows += [
            ["Forma de envío", r["clave"], r["n"], r["mediana_h"], r["p90_h"]] for r in disp["by_method"]
        ]
        flex = d["flex"]
        return [
            Sheet(
                "Respuesta a preguntas",
                ["Quién", *time_headers, "% en menos de 1 h", "% en menos de 12 h"],
                resp_rows,
                note=self.note() + " Preguntas de Mercado Libre respondidas en el período.",
            ),
            Sheet(
                "Tiempo de despacho",
                ["Agrupado por", "Valor", *time_headers],
                disp_rows,
                note=self.note()
                + " Desde Nuevo (pago confirmado) hasta Despachado o Listo para retirar. Sin Full.",
            ),
            Sheet(
                "Flex y Colecta tarde",
                ["Pedido", "Modalidad", "Despachar antes de", "Despachado", "Demora (h)"],
                [
                    [
                        r["pedido"],
                        r["modalidad"],
                        r["limite"],
                        "Todavía sin despachar" if r["sin_despachar"] else r["despachado"],
                        r["demora_h"],
                    ]
                    for r in flex["late"]
                ],
                note=self.note()
                + " Por fecha límite. Tarde: salieron después de la fecha límite o vencieron y siguen sin"
                + " despachar (demora hasta ahora)."
                + f" A tiempo: {flex['on_time']} de {flex['total']}"
                + (f" ({flex['pct']} %)." if flex["pct"] is not None else "."),
            ),
            Sheet(
                "Manuales pendientes",
                ["Pedido", "Cliente", "Fecha", "Días", "Total", "Falta", "Estado"],
                [
                    [r["pedido"], r["cliente"], r["fecha"], r["dias"], r["total"], r["falta"], r["estado"]]
                    for r in d["manual"]["rows"]
                ],
                totals=["Total", "", "", "", d["manual"]["total"], "", ""],
                money_columns={4},
                note="Pedidos manuales sin cobrar o sin facturar a la fecha (no depende del período).",
            ),
        ]


class WholesaleView(ReportView):
    """M8a · US-9: ventas mayoristas por cliente y por quién cargó, pendientes y saldos a favor."""

    template_name = "reports/wholesale.html"
    tab = "reports:wholesale"
    excel_name = "reporte-mayorista"

    def note(self) -> str:
        return f"Período: {self.f.label} · canal Mayorista. Neto = sin IVA; total = con IVA y menos saldo a favor usado."

    def get_context_data(self, **kwargs):
        return super().get_context_data(data=queries.wholesale(self.f), **kwargs)

    def sheets(self):
        d = queries.wholesale(self.f)
        sales_headers = ["Pedidos", "Neto sin IVA", "Total"]
        pending_headers = ["Pedido", "Cliente", "Fecha", "Días", "Total", "Estado"]

        def pending(rows):
            return [[r["pedido"], r["cliente"], r["fecha"], r["dias"], r["total"], r["estado"]] for r in rows]

        today_note = "A la fecha, sin importar el período."
        ct = d["customers_total"]
        return [
            Sheet(
                "Ventas por cliente",
                ["Cliente", *sales_headers],
                [[r["clave"], r["pedidos"], r["neto"], r["total"]] for r in d["customers"]],
                totals=["Total", ct["pedidos"], ct["neto"], ct["total"]],
                money_columns={2, 3},
                note=self.note(),
            ),
            Sheet(
                "Ventas por quién cargó",
                ["Cargado por", *sales_headers],
                [[r["clave"], r["pedidos"], r["neto"], r["total"]] for r in d["sellers"]],
                money_columns={2, 3},
                note=self.note(),
            ),
            Sheet(
                "Esperando pago",
                pending_headers,
                pending(d["awaiting"]),
                money_columns={4},
                note=today_note,
            ),
            Sheet(
                "Vencidos",
                pending_headers,
                pending(d["expired"]),
                money_columns={4},
                note=self.note() + " Transferencias canceladas al vencer el plazo de pago.",
            ),
            Sheet(
                "Sin facturar",
                pending_headers,
                pending(d["not_invoiced"]),
                money_columns={4},
                note=today_note + " Pagados o en curso, sin «Facturado en Contabilium».",
            ),
            Sheet(
                "Reservado sin facturar",
                ["Pedido", "Cliente", "Fecha", "Días", "Estado", "Unidades reservadas", "Total"],
                [
                    [r["pedido"], r["cliente"], r["fecha"], r["dias"], r["estado"], r["unidades"], r["total"]]
                    for r in d["reserved"]
                ],
                totals=["Total", "", "", "", "", d["reserved_units"], ""],
                money_columns={6},
                note=today_note
                + " Unidades que la tienda tiene descontadas por pedidos sin «Facturado en Contabilium».",
            ),
            Sheet(
                "Saldos a favor",
                ["Cliente", "Saldo a favor"],
                [[r["clave"], r["saldo"]] for r in d["balances"]],
                totals=["Total", d["balances_total"]],
                money_columns={1},
                note="Saldos vigentes a la fecha.",
            ),
        ]
