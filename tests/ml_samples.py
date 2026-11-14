"""Respuestas de ejemplo de la API de Mercado Libre (recortadas a los campos que usamos)."""

import copy

SELLER = "123456789"
BUYER = 987654


def item(item_id="MLA1001", variations=True, **overrides):
    data = {
        "id": item_id,
        "title": "Buzo Canguro Oversize Deutsch",
        "status": "active",
        "listing_type_id": "gold_special",
        "category_id": "MLA109042",
        "permalink": f"https://articulo.mercadolibre.com.ar/{item_id}",
        "price": 45000,
        "currency_id": "ARS",
        "available_quantity": 15,
        "sold_quantity": 40,
        "health": 0.85,
        "last_updated": "2026-11-10T12:00:00.000Z",
        "shipping": {"logistic_type": "self_service", "mode": "me2"},
        "attributes": [{"id": "BRAND", "value_name": "Deutsch"}],
        "pictures": [
            {"id": "P1", "secure_url": "https://http2.mlstatic.com/p1.jpg"},
            {"id": "P2", "secure_url": "https://http2.mlstatic.com/p2.jpg"},
        ],
        "variations": [
            {
                "id": 111,
                "price": 45000,
                "available_quantity": 10,
                "picture_ids": ["P2"],
                "attribute_combinations": [
                    {"name": "Talle", "value_name": "M"},
                    {"name": "Color", "value_name": "Negro"},
                ],
                "attributes": [{"id": "SELLER_SKU", "value_name": "BUZ-001-M-NEG"}],
            },
            {
                "id": 112,
                "price": 45000,
                "available_quantity": 5,
                "picture_ids": ["P1"],
                "attribute_combinations": [
                    {"name": "Talle", "value_name": "L"},
                    {"name": "Color", "value_name": "Negro"},
                ],
                "attributes": [],
                "seller_custom_field": "BUZ-001-L-NEG",
            },
        ]
        if variations
        else [],
    }
    if not variations:
        data["attributes"].append({"id": "SELLER_SKU", "value_name": "GOR-010"})
    data.update(overrides)
    return copy.deepcopy(data)


def order(
    order_id=2000001,
    pack_id=None,
    item_id="MLA1001",
    variation_id=111,
    sku="BUZ-001-M-NEG",
    updated="2026-11-12T15:00:00.000-03:00",
    status="paid",
    shipping_id=40001,
    **overrides,
):
    data = {
        "id": order_id,
        "pack_id": pack_id,
        "status": status,
        "tags": ["paid"] if status == "paid" else [],
        "date_created": "2026-11-12T14:00:00.000-03:00",
        "date_last_updated": updated,
        "currency_id": "ARS",
        "total_amount": 45000,
        "paid_amount": 45000,
        "shipping": {"id": shipping_id},
        "buyer": {"id": BUYER, "nickname": "LUCIAG", "first_name": "Lucía", "last_name": "Gómez"},
        "order_items": [
            {
                "item": {
                    "id": item_id,
                    "title": "Buzo Canguro Oversize Deutsch",
                    "variation_id": variation_id,
                    "seller_sku": sku,
                    "variation_attributes": [{"name": "Talle", "value_name": "M"}],
                },
                "quantity": 1,
                "unit_price": 45000,
            }
        ],
        "payments": [
            {
                "id": order_id + 5,
                "status": "approved",
                "transaction_amount": 45000,
                "date_approved": "2026-11-12T14:01:00.000-03:00",
            }
        ],
    }
    data.update(overrides)
    return copy.deepcopy(data)


def shipment(shipment_id=40001, order_id=2000001, logistic="self_service", status="ready_to_ship"):
    return {
        "id": shipment_id,
        "order_id": order_id,
        "logistic_type": logistic,
        "status": status,
        "substatus": "ready_to_print",
        "tracking_number": "TRK123",
        "shipping_option": {
            "name": "Flex",
            "estimated_handling_limit": {"date": "2026-11-13T12:00:00.000-03:00"},
        },
        "status_history": {"date_shipped": None},
        "receiver_address": {"address_line": "Av. Corrientes 1234", "city": {"name": "CABA"}},
    }


def billing(kind="RI"):
    if kind == "RI":
        return {
            "billing_info": {
                "doc_type": "CUIT",
                "doc_number": "30712345678",
                "additional_info": [
                    {"type": "BUSINESS_NAME", "value": "Ropa Lucía SRL"},
                    {"type": "TAXPAYER_TYPE_ID", "value": "IVA Responsable Inscripto"},
                    {"type": "STREET_NAME", "value": "Av. Corrientes"},
                    {"type": "STREET_NUMBER", "value": "1234"},
                    {"type": "CITY_NAME", "value": "CABA"},
                    {"type": "STATE_NAME", "value": "Capital Federal"},
                    {"type": "ZIP_CODE", "value": "1043"},
                ],
            }
        }
    return {
        "billing_info": {
            "doc_type": "DNI",
            "doc_number": "30111222",
            "additional_info": [
                {"type": "FIRST_NAME", "value": "Lucía"},
                {"type": "LAST_NAME", "value": "Gómez"},
                {"type": "TAXPAYER_TYPE_ID", "value": "Consumidor Final"},
            ],
        }
    }


def question(qid=9001, status="UNANSWERED", item_id="MLA1001", answer=None):
    return {
        "id": qid,
        "item_id": item_id,
        "text": "¿Tenés talle XL?",
        "status": status,
        "date_created": "2026-11-12T10:00:00.000-03:00",
        "from": {"id": BUYER},
        "answer": answer,
    }


def message(mid="msg-1", pack_id=None, order_id=2000001, from_seller=False, text="Hola, ¿cuándo llega?"):
    sender, receiver = (SELLER, BUYER) if from_seller else (BUYER, SELLER)
    return {
        "id": mid,
        "from": {"user_id": sender},
        "to": {"user_id": receiver},
        "text": text,
        "message_date": {"created": "2026-11-12T16:00:00.000-03:00"},
        "message_resources": [{"id": str(pack_id or order_id), "name": "packs" if pack_id else "orders"}],
        "message_attachments": [],
    }


def claim(
    cid=5001, order_id=2000001, status="opened", with_return=False, due="2026-11-15T12:00:00.000-03:00"
):
    return {
        "id": cid,
        "resource": "order",
        "resource_id": order_id,
        "type": "mediations",
        "stage": "claim",
        "status": status,
        "reason_id": "PDD9939",
        "players": [
            {"role": "complainant", "type": "buyer", "available_actions": []},
            {
                "role": "respondent",
                "type": "seller",
                "available_actions": [{"action": "send_message_to_complainant", "due_date": due}],
            },
        ],
        "related_entities": ["return"] if with_return else [],
    }
