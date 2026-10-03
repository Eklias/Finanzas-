# Carga del plan de cuentas de clase

Desde la raíz del proyecto, con el entorno virtual activo:

```console
python manage.py migrate
python manage.py cargar_plan_cuentas
```

En PowerShell también puedes usar directamente el entorno del proyecto:

```powershell
.\.venv\Scripts\python.exe manage.py migrate
.\.venv\Scripts\python.exe manage.py cargar_plan_cuentas
```

El catálogo contiene **64 cuentas**: 28 de activo, 10 de pasivo, 6 de
patrimonio, 10 de gasto y 10 de ingreso. No añade clases 8 o 9 ni subcuentas.
Las cuentas personalizadas existentes se conservan, incluso si pertenecen a
las clases excluidas. Por eso el total puede superar 64 en otras bases.

## Conservación e idempotencia

El comando carga en una transacción y busca cada cuenta por su código único.
Nunca elimina cuentas, asientos ni movimientos. Actualiza los nombres del
catálogo manteniendo los identificadores y las relaciones existentes.
Una segunda ejecución no duplica ni vuelve a guardar registros iguales.

Para cuentas sin movimientos actualiza también tipo y subcategoría. Si una
cuenta tiene movimientos, conserva ambos campos y muestra avisos por las
diferencias, incluso cuando la subcategoría anterior está vacía. Revisar esos
avisos permite decidir una reclasificación futura sin cambiar ahora los
resultados históricos. Una cuenta existente con tipo incompatible queda
conservada y avisada; el comando no afirma haber corregido ese conflicto.

**No usar `cargar_prueba` ni `load_case.py` para ampliar una base existente:**
ambos cargadores anteriores eliminan datos antes de crear su caso de prueba.

## Subcategorías e integración

La migración 0003 amplía las opciones de `subcategoria`; no carga el catálogo,
no cambia tipos ni añade campos. Conserva las opciones de EE.RR. anteriores.
Se añaden Activo corriente, Existencias, Activo no corriente, Pasivo,
Patrimonio, Gastos e Ingresos. Las agrupaciones del balance son informativas;
no crean un balance separado entre corriente y no corriente.

Para cuentas nuevas, 60 conserva `costo_ventas`, como en los cargadores
anteriores; 69 usa también `costo_ventas`. 67 usa `gasto_financiero`, 66 usa
`otro_gasto`, los demás gastos usan `gastos`. 70 usa `ingresos` y 71–79
`otro_ingreso`. Estas categorías reutilizan los filtros actuales de reportes.
La agrupación histórica de una cuenta utilizada prevalece sobre estas opciones.

Plan de Cuentas, registro/edición de asientos y chatbot consultan todas las
cuentas, incluidas las que no tienen movimientos. El chatbot continúa siendo
de solo lectura hasta que el usuario guarda un asiento desde el formulario.
Sus pruebas usan un proveedor simulado, sin llamadas reales a Groq.

## Reportes y limitaciones

29, 36 y 39 mantienen tipo `activo`. Sus saldos acreedores se muestran como
importes negativos y restan del activo en Balance General, también al exportar.
Balance de Comprobación los muestra como saldos acreedores reales.
No se añade una naturaleza correctora: `naturaleza_deudora` sigue dependiendo
solo del tipo, de modo que Libro Mayor sitúa esas cuentas como deudoras con
saldo negativo. Representar su naturaleza y presentación explícitamente requiere
un diseño adicional del modelo y los reportes antes de una modificación mayor.
74 conserva el tipo `ingreso` del catálogo: un saldo deudor reduce la utilidad.

Durante la revisión se corrigieron tres inconsistencias previas del reporte
exportado para seguir las fórmulas ya utilizadas en pantalla:

- Incluir otros ingresos y otros gastos en la utilidad y desglosarlos en PDF,
  Excel y CSV.
- Calcular el Mayor de los gastos con Debe menos Haber.
- Conservar el signo de saldos deudores de pasivo y patrimonio, evitando `abs()`.

El Estado de Resultados sigue usando el impuesto estimado fijo del 30% que ya
tenía la aplicación. El Balance General sigue incorporando el resultado antes
de ese impuesto estimado. No se introducen reglas de cierre, compensación de
cuentas por naturaleza, impuestos o reclasificaciones automáticas.

## Pruebas

```powershell
.\.venv\Scripts\python.exe manage.py test
node --test tests/chatbot.test.cjs tests/registrar_asiento.test.cjs
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
```

Se verifica la carga inicial, repetición, códigos únicos, conservación de
cuentas y movimientos, rollback, clasificación, listado, selección y guardado
de asientos, catálogo completo del chatbot y saldos de los cinco reportes,
incluidas correctoras y exportaciones.
