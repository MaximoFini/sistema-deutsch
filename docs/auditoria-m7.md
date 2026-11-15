# Auditoría M7 (2026-11-15)

Revisión de los reportes. Probé con datos armados a mano, con resultados conocidos:
- pedidos de los tres canales;
- uno cancelado;
- uno a las 23:30 del último día del mes;
- comisiones y costo de envío de Mercado Libre;
- Flex a tiempo y Flex vencido.

**Lo que está bien:**
- El bruto del resumen coincide con todas las tablas.
- El neto del resumen coincide con las tablas por canal y por período.
- Los cancelados no suman.
- El pedido de las 23:30 cae en el mes correcto (hora Argentina).
- Las claves de atributos con mayúscula ("Talle") se agrupan igual que en minúscula.
- Lo no vinculado aparece aparte.
- El rendimiento está dentro de lo pedido.

## Hallazgos

| # | Gravedad | Hallazgo | Corrección |
|---|---|---|---|
| R1 | **Media-alta** | **"Flex/Colecta a tiempo" muestra 100 % aunque haya pedidos atrasados.** Solo cuenta los pedidos ya despachados. Un Flex cuya fecha límite pasó y que todavía no salió no aparece en ningún lado. En la prueba, con uno a tiempo y uno vencido sin despachar, decía 100 %. | Tomar el período por **fecha límite** y no por fecha de despacho. Contar como tarde también los que vencieron y siguen sin despachar (no cancelados), marcados "Todavía sin despachar" en la lista, con la demora hasta ahora. Los que tienen fecha límite futura no cuentan. |
| R2 | Media | **Dos "netos" distintos sin explicación.** Agrupando por producto, variante, talle o color, el total de neto no descuenta el costo de envío del vendedor (no se puede repartir entre productos). Por eso no coincide con el neto del resumen: en la prueba, $3.310 contra $2.810, y nada lo aclara en esa fila. | En esas agrupaciones, debajo del total: "Neto sin descontar envíos de Mercado Libre ($500,00). El neto del resumen, con envíos, es $2.810,00." Mismo texto como nota en el Excel. |
| R3 | Baja | **Test de rendimiento inestable.** `test_reports_volume_under_two_seconds` mide el tiempo de reloj y falló una vez en una corrida local con la máquina cargada; solo, pasa. En el CI de GitHub, con máquinas compartidas, puede fallar sin que haya un problema real. | Mantener el límite de consultas, que es exacto. Para el tiempo, medir la mejor de 2 corridas y usar 2 s en local y 4 s si corre en CI (variable `CI`). |
