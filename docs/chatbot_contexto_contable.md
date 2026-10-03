# Contexto contable del chatbot

La fuente es `AsientoContable` y `Movimiento`. Cada hecho consulta nuevamente la base de datos. Las propuestas pendientes y las conversaciones no forman parte del saldo. Para introducir un ejercicio hecho por hecho, revisar y guardar cada propuesta antes de introducir la siguiente.

`core/services/contexto_contable.py` selecciona cuentas por concepto, nombre y código; agrupa Debe y Haber con Decimal hasta la fecha de corte, separa el movimiento del mes y el saldo anterior. Los importes JSON se expresan como cadenas decimales para conservar precisión. Sin movimientos, el saldo es `null`, no un saldo real supuesto de cero.

Límites: 50 cuentas para agregados, 20 asientos y 100 líneas para antecedentes, 400 caracteres por descripción, 200 cuentas de catálogo priorizando las pertinentes. Los agregados no se calculan a partir de la muestra. Se informa si las cuentas o el detalle fueron truncados; un inventario ambiguo o parcialmente seleccionado requiere aclaración.

Una fecha explícita fija el corte y excluye movimientos futuros. Un cierre con mes y año explícitos usa el último día de ese mes. Un cierre sin período solo se infiere si los asientos registrados pertenecen a un único mes y año. Cero meses o varios períodos requieren aclaración; no se escoge el último asiento.

Para inventario final, se calcula saldo registrado menos final informado. Se informa también la suma de entradas del período cuya descripción contiene «compra»: es una pista explícitamente etiquetada, no una clasificación certificada ni una presunción sobre otras entradas. Los aportes y salidas afectan al saldo acumulado. Con varias cuentas de inventario se pide atribuir el saldo.

La diferencia no acredita su causa. Sin tratamiento explícito, se devuelve `requiere_aclaracion` con pregunta, motivo, datos detectados y faltantes. Se reconocen instrucciones afirmativas como «registrar la diferencia como costo de ventas» o «registrar el faltante como pérdida»; otras formulaciones pueden requerir aclaración. Los tratamientos confirmados de inventario con una cuenta inequívoca generan una propuesta local; si falta la contrapartida, se solicita. Los demás casos pueden requerir el proveedor. Una propuesta de inventario además debe coincidir con la diferencia calculada por el servidor. Debe = Haber solo valida el cuadre matemático.

## Ejercicio

1. 08/07/2020: proponer Efectivo Debe 100000, Capital Haber 100000; revisar y guardar.
2. 20/07/2020: proponer Mercaderías Debe 50000, Efectivo Haber 50000; revisar y guardar.
3. 25/07/2020: proponer Cuentas por cobrar Debe 70000, Ventas Haber 70000; revisar y guardar. No inventar costo ni impuestos ausentes del ejercicio.
4. «31/07/2020 Se pagan gastos operativos por 20,000 soles al contado»: solicitar el tipo de gasto. Responder, por ejemplo, «personal» o «terceros» en la misma sesión; se conservan fecha, importe y pago. Revisar y guardar la propuesta resultante.
5. «En el inventario se observa un saldo final de S/ 10,000 al cierre del mes»: inferir julio de 2020 si es el único período registrado. Detectar compras 50000, saldo registrado 50000, final informado 10000, diferencia 40000. Preguntar si la diferencia corresponde a costo de ventas, pérdida u otra causa.
6. Responder a la aclaración con el tratamiento confirmado, por ejemplo, «registrar la diferencia como costo de ventas». Si el tratamiento queda suficientemente justificado, presentar Costo de ventas Debe 40000 y Mercaderías Haber 40000. Revisar y confirmar para guardar.

Las pruebas usan un proveedor simulado; verifican el contexto enviado y las defensas del servidor, sin consumir Groq ni certificar todas las respuestas posibles del modelo real.

## Aclaraciones temporales en sesión

`chatbot_aclaracion_pendiente` conserva un único mensaje original, datos estructurados detectados (incluida la operación), campos faltantes, pregunta pendiente y la última respuesta por campo pendiente. No conserva un historial. Caduca después de 30 minutos sin actualización; se elimina al obtener una propuesta validada o al enviar «cancelar». Un nuevo hecho con operación, fecha e importe explícitos reemplaza el pendiente, incluso si necesita una aclaración distinta. Los clientes usan sus propias sesiones de Django.

Las respuestas por código o palabras del nombre se cotejan con opciones de la pregunta y cuentas actuales del catálogo. Solo una coincidencia única resuelve una cuenta. Con fecha, importe y pago al contado conocidos, una naturaleza de gasto resuelta permite proponer el pago usando las cuentas existentes y las validaciones comunes. Si aún faltan datos, se preguntan únicamente esos datos y se conserva la cuenta elegida para los siguientes turnos.

Para otras aclaraciones, el proveedor recibe explícitamente mensaje original, datos detectados, datos pendientes, pregunta, contexto estructurado de respuestas anteriores y respuesta nueva. Cada turno consulta nuevamente el catálogo y los saldos. Las respuestas siguen validándose contra las cuentas reales, fecha detectada, importes positivos y cuadre del asiento. El navegador ya envía las cookies con `credentials: 'same-origin'`; no necesita guardar conversaciones ni enviar nuevamente el hecho completo.

## Resolución general de aclaraciones

Cada pregunta conserva su campo pendiente y opciones estructuradas (`id`, `label`, `sinonimos`, `valor`), además del contexto contable. Se admiten las opciones antiguas con `etiqueta`. El resolver local acepta nombres, sinónimos, códigos, números visibles y ordinales; solo una coincidencia inequívoca completa el dato. «En efectivo» es una alternativa de pago al contado. Las expresiones de duda o varias alternativas no seleccionan una cuenta por descarte.

«Sí» o «esa opción» requieren una alternativa propuesta explícitamente. Una negación retira ese referente; un «sí» posterior no confirma la alternativa rechazada. Las respuestas inválidas o ambiguas mantienen la aclaración y no llaman al proveedor. La resolución semántica remota solo se usa si el llamador la solicita pasando un proveedor al resolver.

Las consultas informativas muestran las opciones numeradas y preservan sus identificadores. Para inventarios y tipos de gasto también puede consultarse el catálogo vigente. Si desaparece una cuenta entre la pregunta y la respuesta, se presenta la lista actual antes de interpretar otra selección, evitando asignar un número antiguo a otra cuenta. Si no quedan cuentas elegibles, se mantiene la aclaración hasta revisar el catálogo o cancelar. No se guarda ningún asiento al resolver: la propuesta sigue requiriendo revisión y confirmación.

Verificación local: `.venv\Scripts\python.exe manage.py test --noinput` y `node --test tests/*.test.cjs`. Los casos de regresión incluyen selección ambigua, negación seguida de afirmación, pago en efectivo, opciones de campos generales y cambios de catálogo entre turnos.

## Ambigüedad de gastos y errores del proveedor

`core/services/aclaraciones_contables.py` detecta «gastos operativos» sin una naturaleza específica antes de llamar a Groq. Devuelve HTTP 200 y `estado: requiere_aclaracion`, con `pregunta`, `motivo`, `datos_detectados` y `datos_faltantes`. Las opciones usan nombres y códigos de cuentas de gasto existentes en la base de datos, no un catálogo inventado ni códigos fijos.

En el ejemplo del paso 4 conserva `fecha: 2020-07-31`, `importe: 20000.00`, `moneda: PEN` y `forma_pago: al contado`. Si existe una sola cuenta de efectivo identificable, conserva también la contrapartida al Haber por 20000.00. Con el catálogo de clase es la cuenta 10. Solo falta `tipo_gasto_operativo`; no se crea un asiento parcial ni se elige 62, 63, 64 o 65 por descarte. Sin fecha se pide también la fecha, conservando el resto. Con varias cuentas de efectivo no se selecciona una arbitrariamente.

Los conceptos explícitos (gastos de personal, servicios de terceros, tributos, otros gastos de gestión) siguen el flujo de evaluación y validación del proveedor. Las aclaraciones que devuelve Groq también conservan los datos explícitos detectados localmente. El HTTP 502 continúa reservado para errores de transporte/proveedor o contenido imposible de procesar; la ambigüedad contable no genera ese error.

La interfaz ya muestra las aclaraciones HTTP 200 como preguntas normales. No es necesario cambiar su manejo de errores. El mensaje «No se pudo obtener una respuesta de Groq» procede de una excepción HTTP/transporte: antes faltaba la validación local para evitar enviar este hecho ambiguo al proveedor. Sin el diagnóstico del intento original no se puede determinar el error HTTP concreto que devolvió Groq.
