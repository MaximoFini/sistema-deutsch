"""Respuestas de ejemplo de la API de Tiendanube 2025-03 (recortadas a los campos que usamos)."""

import copy


def product(product_id=1001, updated_at="2026-11-10T12:00:00+0000", **overrides):
    data = {
        "id": product_id,
        "name": {"es": "Buzo Canguro Oversize"},
        "description": {"es": "<p>Buzo de frisa</p>"},
        "handle": {"es": "buzo-canguro-oversize"},
        "brand": "Deutsch",
        "visibility": "visible",
        "published": True,
        "attributes": [{"es": "Talle"}, {"es": "Color"}],
        "categories": [{"id": 1, "name": {"es": "Buzos"}}, {"id": 2, "name": {"es": "Invierno"}}],
        "images": [
            {"id": 2, "src": "https://cdn.example/b2.jpg", "position": 2, "alt": {"es": ""}},
            {"id": 1, "src": "https://cdn.example/b1.jpg", "position": 1, "alt": {"es": "Frente"}},
        ],
        "updated_at": updated_at,
        "variants": [
            {
                "id": 5001,
                "sku": "BUZ-001-M-NEG",
                "barcode": "7790000000011",
                "values": [{"es": "M"}, {"es": "Negro"}],
                "price": "45000.00",
                "promotional_price": "39900.00",
                "stock": 12,
                "weight": "0.650",
                "width": "30.00",
                "height": "5.00",
                "depth": "40.00",
                "updated_at": updated_at,
            },
            {
                "id": 5002,
                "sku": "BUZ-001-L-NEG",
                "barcode": None,
                "values": [{"es": "L"}, {"es": "Negro"}],
                "price": "45000.00",
                "promotional_price": None,
                "stock": 3,
                "weight": "0.700",
                "width": "30.00",
                "height": "5.00",
                "depth": "40.00",
                "updated_at": updated_at,
            },
        ],
    }
    data.update(overrides)
    return copy.deepcopy(data)


def order(order_id=9001, updated_at="2026-11-12T15:00:00+0000", **overrides):
    data = {
        "id": order_id,
        "number": 1234,
        "token": "tok",
        "status": "open",
        "payment_status": "paid",
        "shipping_status": "unpacked",
        "currency": "ARS",
        "created_at": "2026-11-12T14:00:00+0000",
        "updated_at": updated_at,
        "paid_at": "2026-11-12T14:05:00+0000",
        "gateway": "mercadopago",
        "gateway_name": "Mercado Pago",
        "subtotal": "84900.00",
        "discount": "4900.00",
        "shipping_cost_customer": "5500.00",
        "total": "85500.00",
        "note": "Tocar timbre 2B",
        "contact_name": "Lucía Gómez",
        "contact_email": "Lucia@Example.com",
        "contact_phone": "+5491155550000",
        "contact_identification": "30111222",
        "customer": {
            "id": 777,
            "name": "Lucía Gómez",
            "email": "lucia@example.com",
            "identification": "30111222",
        },
        "shipping_pickup_type": "ship",
        "shipping_option": "Envío Nube - Correo Argentino a domicilio",
        "shipping_option_code": "envio-nube-correo-argentino",
        "shipping_tracking_number": None,
        "shipping_address": {
            "name": "Lucía Gómez",
            "address": "Av. Corrientes",
            "number": "1234",
            "floor": "2B",
            "locality": "Balvanera",
            "city": "CABA",
            "province": "Capital Federal",
            "zipcode": "1043",
            "country": "AR",
        },
        "products": [
            {
                "id": 1,
                "product_id": 1001,
                "variant_id": 5001,
                "name": "Buzo Canguro Oversize",
                "sku": "BUZ-001-M-NEG",
                "price": "39900.00",
                "quantity": 1,
                "variant_values": ["M", "Negro"],
            },
            {
                "id": 2,
                "product_id": 1001,
                "variant_id": 5002,
                "name": "Buzo Canguro Oversize",
                "sku": "BUZ-001-L-NEG",
                "price": "45000.00",
                "quantity": 1,
                "variant_values": ["L", "Negro"],
            },
        ],
    }
    data.update(overrides)
    return copy.deepcopy(data)


def pickup_order(order_id=9002, **overrides):
    return order(
        order_id=order_id,
        number=1235,
        shipping_pickup_type="pickup",
        shipping_option="Retiro en el local",
        shipping_option_code="pickup-local",
        gateway="offline",
        gateway_name="Transferencia bancaria",
        payment_status="pending",
        **overrides,
    )


def fulfillment_orders(status="UNPACKED", shipping_type="ship"):
    return [{"id": "01HXFO000000000000000000AA", "status": status, "shipping": {"type": shipping_type}}]
