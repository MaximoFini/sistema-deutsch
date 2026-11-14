"""Numeración interna sin colisiones: una secuencia de Postgres por tipo de documento.

Las secuencias se crean en la migración 0002 de `sales`.
"""

from django.db import connection

SEQUENCES = {
    "order": "sales_number_order_seq",
    "return": "sales_number_return_seq",
    "invoice": "sales_number_invoice_seq",
    "credit_note": "sales_number_credit_note_seq",
    "debit_note": "sales_number_debit_note_seq",
}


def next_number(doc_type: str) -> int:
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval(%s)", [SEQUENCES[doc_type]])
        return cursor.fetchone()[0]
