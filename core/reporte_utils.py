from decimal import Decimal
from django.db.models import Sum, Q
from .models import CuentaContable, AsientoContable, Movimiento

def get_reporte_context():
    ctx = {}
    # Traemos todo ordenado en una sola consulta eficiente
    ctx['asientos'] = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id')
    
    cuentas = CuentaContable.objects.all()
    bal_comp_datos = []
    
    # OPTIMIZACIÓN CLAVE: Obtenemos todos los totales de una sola vez
    totales = Movimiento.objects.values('cuenta_id', 'tipo').annotate(total=Sum('monto'))
    mapa_totales = {}
    for t in totales:
        if t['cuenta_id'] not in mapa_totales: mapa_totales[t['cuenta_id']] = {'debe': Decimal('0'), 'haber': Decimal('0')}
        mapa_totales[t['cuenta_id']][t['tipo']] = t['total']

    gran_total_debe = gran_total_haber = gran_saldo_deudor = gran_saldo_acreedor = Decimal('0')

    for cuenta in cuentas:
        tot = mapa_totales.get(cuenta.id, {'debe': Decimal('0'), 'haber': Decimal('0')})
        total_debe, total_haber = tot['debe'], tot['haber']
        
        if total_debe == 0 and total_haber == 0: continue
            
        saldo = total_debe - total_haber
        saldo_deudor = saldo if saldo > 0 else Decimal('0')
        saldo_acreedor = abs(saldo) if saldo < 0 else Decimal('0')
        
        bal_comp_datos.append({
            'cuenta': cuenta, 'total_debe': total_debe, 'total_haber': total_haber,
            'saldo_deudor': saldo_deudor, 'saldo_acreedor': saldo_acreedor
        })
        
        gran_total_debe += total_debe
        gran_total_haber += total_haber
        gran_saldo_deudor += saldo_deudor
        gran_saldo_acreedor += saldo_acreedor

    ctx.update({
        'bal_comp_datos': bal_comp_datos,
        'gran_total_debe': gran_total_debe, 'gran_total_haber': gran_total_haber,
        'gran_saldo_deudor': gran_saldo_deudor, 'gran_saldo_acreedor': gran_saldo_acreedor
    })
    
    # Estado de Resultados simplificado (usando totales ya calculados)
    def total_por_filtro(tipo_cuenta, subcat=None, exclude_subcat=None):
        qs = cuentas.filter(tipo=tipo_cuenta)
        if subcat: qs = qs.filter(subcategoria=subcat)
        if exclude_subcat: qs = qs.exclude(subcategoria__in=exclude_subcat)
        suma = Decimal('0')
        for c in qs:
            t = mapa_totales.get(c.id, {'debe': Decimal('0'), 'haber': Decimal('0')})
            suma += (t['debe'] - t['haber']) if tipo_cuenta == 'gasto' else (t['haber'] - t['debe'])
        return suma

    ctx['er_total_ventas'] = total_por_filtro('ingreso', exclude_subcat=['otro_ingreso'])
    ctx['er_total_costo_ventas'] = total_por_filtro('gasto', subcat='costo_ventas')
    ctx['er_utilidad_bruta'] = ctx['er_total_ventas'] - ctx['er_total_costo_ventas']
    ctx['er_total_gastos_operativos'] = total_por_filtro('gasto', exclude_subcat=['costo_ventas', 'gasto_financiero', 'otro_gasto'])
    ctx['er_utilidad_operativa'] = ctx['er_utilidad_bruta'] - ctx['er_total_gastos_operativos']
    ctx['er_total_gastos_financieros'] = total_por_filtro('gasto', subcat='gasto_financiero')
    ctx['er_utilidad_antes_impuesto'] = ctx['er_utilidad_operativa'] - ctx['er_total_gastos_financieros']
    ctx['er_impuesto'] = (ctx['er_utilidad_antes_impuesto'] * Decimal('0.30')).quantize(Decimal('0.01')) if ctx['er_utilidad_antes_impuesto'] > 0 else Decimal('0')
    ctx['er_utilidad_neta'] = ctx['er_utilidad_antes_impuesto'] - ctx['er_impuesto']

    # --- NUEVO: Lógica del Balance General ---
    bg_activos = []
    bg_pasivos = []
    bg_patrimonio = []
    total_activos = total_pasivos = total_patrimonio = Decimal('0')

    for cuenta in cuentas:
        t = mapa_totales.get(cuenta.id, {'debe': Decimal('0'), 'haber': Decimal('0')})
        saldo = t['debe'] - t['haber']
        if cuenta.tipo == 'activo':
            if saldo != 0:
                bg_activos.append({'cuenta': cuenta, 'saldo': saldo})
                total_activos += saldo
        elif cuenta.tipo == 'pasivo':
            saldo_acreedor = abs(saldo)
            if saldo_acreedor != 0:
                bg_pasivos.append({'cuenta': cuenta, 'saldo': saldo_acreedor})
                total_pasivos += saldo_acreedor
        elif cuenta.tipo == 'patrimonio':
            saldo_acreedor = abs(saldo)
            if saldo_acreedor != 0:
                bg_patrimonio.append({'cuenta': cuenta, 'saldo': saldo_acreedor})
                total_patrimonio += saldo_acreedor

    ctx.update({
        'bg_activos': bg_activos,
        'bg_pasivos': bg_pasivos,
        'bg_patrimonio': bg_patrimonio,
        'bg_total_activos': total_activos,
        'bg_total_pasivos': total_pasivos,
        'bg_resultados_acumulados': ctx['er_utilidad_antes_impuesto'],
        'bg_total_patrimonio': total_patrimonio + ctx['er_utilidad_antes_impuesto'],
        'bg_total_pasivo_patrimonio': total_pasivos + total_patrimonio + ctx['er_utilidad_antes_impuesto'],
    })

    # Traer Libro Mayor también
    mayor_datos = []
    for cuenta in cuentas:
        movs = Movimiento.objects.filter(cuenta=cuenta).select_related('asiento').order_by('asiento__fecha')
        if movs.exists():
            t = mapa_totales.get(cuenta.id, {'debe': Decimal('0'), 'haber': Decimal('0')})
            mayor_datos.append({
                'cuenta': cuenta, 'movimientos': movs,
                'total_debe': t['debe'], 'total_haber': t['haber'],
                'saldo_final': t['debe'] - t['haber'] if cuenta.tipo == 'activo' else t['haber'] - t['debe']
            })
    ctx['mayor_datos'] = mayor_datos

    return ctx