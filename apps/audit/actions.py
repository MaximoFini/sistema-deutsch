"""Catálogo de acciones auditadas. Cada módulo registra las suyas con `audit.record`.

El texto es lo que ve el administrador en la pantalla de Auditoría.
"""

ACTIONS: dict[str, str] = {
    # M0 · usuarios y sistema
    "user.created": "Usuario creado",
    "user.updated": "Usuario editado",
    "user.deactivated": "Usuario desactivado",
    "user.reactivated": "Usuario reactivado",
    "source_of_truth.changed": "Fuente de verdad cambiada",
    "integration.write_switch_changed": "Interruptor de escritura cambiado",
    "integration.write_blocked": "Escritura a canal bloqueada",
    "integration.event_retried": "Evento de integración reprocesado",
    "integration.connected": "Canal conectado",
    "integration.disconnected": "Canal desconectado",
    "privacy.customer_redacted": "Datos de cliente anonimizados (pedido de privacidad)",
    "catalog.link_changed": "Vínculo de catálogo cambiado",
    "catalog.contabilium_imported": "Archivo de Contabilium importado",
    "alert_type.updated": "Tipo de alerta editado",
    # M4 · pedidos
    "order.status_changed": "Cambio de estado de pedido",
    "order.manual_created": "Pedido manual creado",
    "order.returned": "Devolución registrada",
    "order.payment_updated": "Cobro de pedido actualizado",
    "order.invoice_updated": "Facturación de pedido actualizada",
    "return.expected_created": "Devolución esperada cargada",
    "return.received": "Devolución recibida",
    "return.adjusted": "Devolución ajustada en Contabilium",
    # M5 · preparación y despacho
    "fulfillment.batch_created": "Tanda de preparación armada",
    "fulfillment.order_removed": "Pedido sacado de una tanda",
    "fulfillment.batch_closed": "Tanda de preparación cerrada",
    "fulfillment.carrier_changed": "Lista de expresos editada",
    "shipment.label_printed": "Etiqueta o rótulo de envío impreso",
    # M6 · Mercado Libre
    "ml.question_answered": "Respuesta a pregunta de ML",
    "ml.message_sent": "Mensaje enviado en ML",
    "ml.listing_edited": "Publicación editada",
    "ml.saved_reply_changed": "Respuesta guardada creada o editada",
    # M8 · mayorista
    "client.approved": "Cliente mayorista aprobado",
    "client.rejected": "Cliente mayorista rechazado",
    "payment.confirmed": "Pago confirmado",
    "client.registered": "Registro en la tienda mayorista",
    "client.updated": "Datos de cliente mayorista corregidos",
    "client.suspended": "Cliente mayorista suspendido",
    "client.reactivated": "Cliente mayorista reactivado",
    "client.credit_changed": "Cuenta corriente de cliente mayorista cambiada",
    "wholesale.order_placed": "Pedido mayorista confirmado",
    "wholesale.settings_changed": "Configuración de la tienda mayorista cambiada",
    "wholesale.email_template_changed": "Texto de email a clientes editado",
    "wholesale.receipt_uploaded": "Comprobante de pago subido",
    "wholesale.shortage_reported": "Faltante marcado en un pedido mayorista",
    "wholesale.shortage_resolved": "Pedido mayorista ajustado por faltante",
    "wholesale.acting_started": "Pedido en nombre de un cliente: empezó",
    "wholesale.acting_finished": "Pedido en nombre de un cliente: terminó",
    "client.change_requested": "Cliente mayorista pidió cambiar sus datos",
    "wholesale.order_repeated": "Cliente mayorista repitió un pedido",
    "client.imported": "Cuenta mayorista preparada desde un cliente cargado",
    "invitation.prepared": "Invitaciones mayoristas preparadas",
    "invitation.sent": "Invitaciones mayoristas encoladas para enviar",
    "invitation.dry_run": "Ensayo de envío de invitaciones (no se mandó nada)",
    "invitation.accepted": "Cliente mayorista creó su contraseña por invitación",
    "invitation.requested": "Cliente mayorista pidió otra invitación",
    "invitation.switch": "Envío de invitaciones mayoristas habilitado o apagado",
    "invitation.email_corrected": "Email de un cliente mayorista corregido antes de invitar",
}


def label(action: str) -> str:
    return ACTIONS.get(action, action)
