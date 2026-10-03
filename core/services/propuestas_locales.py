"""Tratamientos confirmados que pueden proponerse sin interpretación remota."""
from decimal import Decimal

from .contexto_contable import aclaracion, normalizar


def proponer_ajuste_inventario(contexto, cuentas, fecha):
    datos = contexto['datos_detectados']
    causa = datos.get('causa_ajuste') or datos.get('causa_y_tratamiento_de_la_diferencia')
    if not causa or 'diferencia' not in datos:
        return None
    causa = normalizar(str(causa))
    costo = causa == 'costo_ventas' or causa in {
        'costo de ventas', 'costo de las mercaderias vendidas', 'costo de mercaderias vendidas'}
    if causa in {'otra', 'otra causa'} and not datos.get('detalle_causa_ajuste'):
        return aclaracion('¿Cuál fue la otra causa y qué tratamiento corresponde?',
                          'Se necesita precisar el tratamiento del ajuste.', datos, ['detalle_causa_ajuste'])
    diferencia = Decimal(datos['diferencia'])
    if diferencia <= 0:
        return aclaracion('La diferencia no representa una disminución del inventario. '
                          '¿Qué ajuste deseas registrar?',
                          'Este tratamiento requiere una disminución positiva.', datos, ['tratamiento_ajuste'])
    por_codigo = {c.codigo: c for c in cuentas}
    inventario = datos.get('cuentas_inventario', [])
    if not fecha or len(inventario) != 1 or inventario[0] not in por_codigo:
        return None
    elegida = datos.get('cuenta_ajuste', {}).get('cuenta_codigo')
    candidatas = [c for c in cuentas if c.tipo == 'gasto' and normalizar(c.nombre) in {
            'costo de ventas', 'costo de las mercaderias vendidas', 'costo de mercaderias vendidas'}] if costo else []
    cuenta = por_codigo.get(elegida) if elegida else (candidatas[0] if len(candidatas) == 1 else None)
    if cuenta is None:
        resultado = aclaracion('¿Qué cuenta corresponde a la contrapartida del ajuste?',
                                'La causa está confirmada; falta una cuenta inequívoca.', datos, ['cuenta_ajuste'])
        resultado['opciones_validas'] = [
            {'id': c.codigo, 'label': c.nombre,
             'valor': {'cuenta_codigo': c.codigo, 'cuenta_nombre': c.nombre}}
            for c in sorted(candidatas or [c for c in cuentas if c.tipo == 'gasto'], key=lambda c: c.codigo)]
        return resultado
    return {'estado': 'propuesta', 'fecha': fecha,
            'descripcion': 'Ajuste de inventario: ' + cuenta.nombre,
            'movimientos': [
                {'cuenta_codigo': cuenta.codigo, 'tipo': 'debe', 'monto': format(diferencia, '.2f')},
                {'cuenta_codigo': inventario[0], 'tipo': 'haber', 'monto': format(diferencia, '.2f')},
            ]}
