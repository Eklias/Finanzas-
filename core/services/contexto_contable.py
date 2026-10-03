"""Contexto de solo lectura: agregados exactos y antecedentes acotados."""
import calendar
import re
import unicodedata
from datetime import date
from decimal import Decimal

from django.db.models import Count, Q, Sum
from django.db.models.functions import TruncMonth

from core.models import AsientoContable, Movimiento
from .fechas import MESES

MAX_CUENTAS = 50
MAX_ASIENTOS = 20
MAX_MOVIMIENTOS = 100


def normalizar(texto):
    return ''.join(c for c in unicodedata.normalize('NFD', texto.lower())
                   if unicodedata.category(c) != 'Mn')


CONCEPTOS = {
    'inventario': ('inventario', 'mercader', 'existencia'),
    'efectivo': ('efectivo', 'caja', 'banco', 'contado'),
    'cobrar': ('cuentas por cobrar', 'clientes', 'cliente', 'credito'),
    'pagar': ('cuentas por pagar', 'proveedor'),
    'ventas': ('venta',),
    'gastos': ('gasto', 'costo'),
    'capital': ('capital', 'aporte', 'patrimonio'),
}


def grupos_cuenta(cuenta):
    nombre = normalizar(cuenta.nombre)
    grupos = {g for g, palabras in CONCEPTOS.items() if any(p in nombre for p in palabras)}
    if cuenta.subcategoria == 'existencias':
        grupos.add('inventario')
    if cuenta.tipo == 'gasto':
        grupos.add('gastos')
    return grupos


def aclaracion(pregunta, motivo, detectados, faltantes):
    return {'estado': 'requiere_aclaracion', 'pregunta': pregunta, 'motivo': motivo,
            'datos_detectados': detectados, 'datos_faltantes': faltantes}


def resolver_periodo(hecho, fecha):
    texto = normalizar(hecho)
    if fecha or not re.search(r'cierre\s+(?:del?\s+)?(?:mes|' + '|'.join(MESES) + ')', texto):
        return fecha, None
    meses = re.findall(r'\b(' + '|'.join(MESES) + r')\s+(?:de\s+)?(\d{4})\b', texto)
    if meses:
        candidatos = {(int(anio), MESES[mes]) for mes, anio in meses}
    else:
        # Dos meses bastan para probar ambigüedad; nunca elegir simplemente el último.
        candidatos = {(f.year, f.month) for f in AsientoContable.objects.order_by()
                      .annotate(mes=TruncMonth('fecha')).values_list('mes', flat=True).distinct()[:2]}
        mencionados = {MESES[m] for m in MESES if re.search(r'\b' + m + r'\b', texto)}
        if mencionados and any(m not in mencionados for _, m in candidatos):
            candidatos = set()
    if len(candidatos) != 1:
        return None, aclaracion('¿A qué mes y año corresponde el cierre?',
                                'Los asientos registrados no determinan un único período.', {}, ['fecha', 'periodo'])
    anio, mes = candidatos.pop()
    if not 1 <= anio <= 9999:
        return None, aclaracion('¿Cuál es el año correcto del cierre?', 'Año inválido.', {}, ['fecha'])
    return date(anio, mes, calendar.monthrange(anio, mes)[1]).isoformat(), None


def construir_contexto(hecho, cuentas, fecha, cuenta_inventario=None):
    texto = normalizar(hecho)
    conceptos = {g for g, palabras in CONCEPTOS.items() if any(p in texto for p in palabras)}
    relevantes = conceptos | ({'ventas', 'gastos'} if 'inventario' in conceptos else set())
    seleccion = [c for c in cuentas if grupos_cuenta(c) & relevantes
                 or normalizar(c.nombre) in texto
                 or re.search((r'\bcuenta\s+' if c.codigo.isdigit() else r'(?<!\w)')
                              + re.escape(c.codigo.lower()) + r'(?!\w)', texto)]
    if cuenta_inventario:
        codigo = cuenta_inventario['cuenta_codigo']
        seleccion = [c for c in seleccion if 'inventario' not in grupos_cuenta(c) or c.codigo == codigo]
        elegida = next((c for c in cuentas if c.codigo == codigo and c.tipo == 'activo'), None)
        if elegida and elegida not in seleccion:
            seleccion.insert(0, elegida)
    truncadas = len(seleccion) > MAX_CUENTAS
    seleccion = seleccion[:MAX_CUENTAS]
    ids = [c.pk for c in seleccion]
    movs = Movimiento.objects.filter(cuenta_id__in=ids)
    if fecha:
        movs = movs.filter(asiento__fecha__lte=fecha)
    inicio = fecha[:7] + '-01' if fecha else None
    periodo = Q(asiento__fecha__gte=inicio) if inicio else Q()
    filas = {f['cuenta_id']: f for f in movs.order_by().values('cuenta_id').annotate(
        cantidad=Count('id'), debe=Sum('monto', filter=Q(tipo='debe')),
        haber=Sum('monto', filter=Q(tipo='haber')),
        debe_periodo=Sum('monto', filter=periodo & Q(tipo='debe')),
        haber_periodo=Sum('monto', filter=periodo & Q(tipo='haber')))}
    saldos = []
    for c in seleccion:
        f = filas.get(c.pk, {})
        d, h = f.get('debe') or Decimal(0), f.get('haber') or Decimal(0)
        dp, hp = f.get('debe_periodo') or Decimal(0), f.get('haber_periodo') or Decimal(0)
        saldos.append({'cuenta_codigo': c.codigo, 'cuenta_nombre': c.nombre,
                       'movimientos_registrados': f.get('cantidad', 0),
                       'total_debe': format(d, '.2f'), 'total_haber': format(h, '.2f'),
                       'saldo_debe_menos_haber': format(d-h, '.2f') if f else None,
                       'saldo_segun_naturaleza': format(d-h if c.naturaleza_deudora else h-d, '.2f') if f else None,
                       'debe_periodo': format(dp, '.2f') if inicio else None,
                       'haber_periodo': format(hp, '.2f') if inicio else None,
                       'saldo_anterior_al_periodo': format(d-h-dp+hp, '.2f') if f and inicio else None})
    anteriores = movs.filter(periodo)
    asiento_ids = list(anteriores.order_by('-asiento__fecha', '-asiento_id')
                       .values_list('asiento_id', flat=True).distinct()[:MAX_ASIENTOS + 1])
    detalle = list(Movimiento.objects.filter(asiento_id__in=asiento_ids[:MAX_ASIENTOS])
                   .select_related('asiento', 'cuenta').order_by('-asiento__fecha', '-asiento_id', 'id')[:MAX_MOVIMIENTOS + 1])
    asientos = {}
    for m in detalle[:MAX_MOVIMIENTOS]:
        a = asientos.setdefault(m.asiento_id, {'id': m.asiento_id, 'fecha': m.asiento.fecha.isoformat(),
                                             'descripcion': m.asiento.descripcion[:400], 'movimientos': []})
        a['movimientos'].append({'cuenta_codigo': m.cuenta.codigo, 'cuenta_nombre': m.cuenta.nombre,
                                 'tipo': m.tipo, 'monto': format(m.monto, '.2f')})
    contexto = {'fuente': 'contabilidad registrada; no memoria del chat',
                'corte': fecha or 'período sin confirmar', 'periodo': fecha[:7] if fecha else None,
                'conceptos': sorted(conceptos), 'saldos': saldos, 'asientos': list(asientos.values()),
                'limites': {'cuentas': MAX_CUENTAS, 'asientos': MAX_ASIENTOS, 'movimientos': MAX_MOVIMIENTOS},
                'cuentas_truncadas': truncadas,
                'detalle_truncado': len(asiento_ids) > MAX_ASIENTOS or len(detalle) > MAX_MOVIMIENTOS,
                'datos_detectados': {}}
    # Un final informado no prueba la causa del ajuste ni la integridad del libro.
    if 'inventario' in conceptos and re.search(r'(?:saldo\s+)?final', texto):
        match = re.search(r'final(?:\s+de)?\s*(?:s/\.?\s*)?(\d+(?:[.,]\d+)*)', texto)
        importe = None
        if match:
            numero = match[1]
            if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?', numero):
                importe = Decimal(numero.replace(',', ''))
        inventarios = [c for c in seleccion if c.tipo == 'activo' and (
            c.codigo == cuenta_inventario['cuenta_codigo'] if cuenta_inventario
            else 'inventario' in grupos_cuenta(c))]
        datos = contexto['datos_detectados']
        datos['cuentas_inventario'] = [c.codigo for c in inventarios]
        datos['inventario_final_informado'] = format(importe, '.2f') if importe is not None else None
        if len(inventarios) == 1 and inventarios[0].pk in filas and importe is not None and fecha:
            c = inventarios[0]
            f = filas[c.pk]
            saldo = (f['debe'] or Decimal(0)) - (f['haber'] or Decimal(0))
            datos['inventario_saldo_registrado'] = format(saldo, '.2f')
            datos['diferencia'] = format(saldo - importe, '.2f')
            # Solo entradas descritas como compra; no confundir aportes o transferencias con compras.
            compras = anteriores.filter(cuenta=c, tipo='debe', asiento__descripcion__icontains='compra').aggregate(total=Sum('monto'))['total']
            datos['inventario_compras_periodo'] = format(compras or Decimal(0), '.2f')
            datos['criterio_compras'] = 'Débitos cuya descripción contiene compra; no clasificación contable certificada.'
    return contexto


def verificar_contexto(hecho, contexto):
    datos = contexto['datos_detectados']
    if 'inventario_final_informado' not in datos:
        return None
    if contexto['cuentas_truncadas'] or len(datos['cuentas_inventario']) != 1:
        return aclaracion('¿A qué cuenta de inventario corresponde el saldo final?',
                          'No se puede atribuir el saldo a una única cuenta.', datos, ['cuenta_inventario'])
    if 'diferencia' not in datos:
        return aclaracion('¿Cuál es el saldo contable previo, la fecha y el importe final del inventario?',
                          'No hay datos suficientes para calcular la diferencia; no se presume saldo cero.',
                          datos, ['saldo_contable_o_importe_final_o_fecha'])
    texto = normalizar(hecho)
    # Afirmaciones explícitas, no una elección automática entre costo, merma o pérdida.
    tratamiento = re.search(r'(?:registrar|reconocer|contabilizar)\b.{0,60}\bcomo\s+(?:perdida|merma|costo de (?:las )?ventas|costo de mercaderias vendidas)', texto)
    confirmado = datos.get('causa_ajuste') or datos.get('causa_y_tratamiento_de_la_diferencia')
    if not confirmado and (not tratamiento or re.search(r'\b(?:no|sin|duda|quizas)\b', texto) or '?' in texto):
        resultado = aclaracion(f"En {contexto['periodo']}, el saldo registrado es S/ {datos['inventario_saldo_registrado']} "
                          f"y el final informado es S/ {datos['inventario_final_informado']}; "
                          f"la diferencia es S/ {datos['diferencia']}. "
                          '¿Corresponde al costo de las mercaderías vendidas, a una pérdida u otra causa?',
                          'El saldo permite calcular la diferencia, pero no justifica por sí solo la contrapartida. Debe = Haber solo valida el cuadre matemático.',
                          datos, ['causa_ajuste'])
        resultado['opciones_validas'] = [
            {'id': 'costo_ventas', 'label': 'Costo de las mercaderías vendidas',
             'sinonimos': ['costo de ventas', 'mercaderías vendidas', 'vendidas']},
            {'id': 'perdida', 'label': 'Pérdida'},
            {'id': 'otra', 'label': 'Otra causa'},
        ]
        return resultado
    return None
