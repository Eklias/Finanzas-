"""Validación compartida de asientos, sin escribir en la base de datos."""
from decimal import Decimal, InvalidOperation
from datetime import date
import re

from core.models import CuentaContable


def validar_fecha(valor):
    """Fecha de calendario en el formato ISO usado por formularios y propuestas."""
    if not isinstance(valor, str) or not re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', valor):
        raise ValueError('La fecha no es válida. Use YYYY-MM-DD.')
    return date.fromisoformat(valor)


def validar_movimientos(movimientos):
    """Devuelve (movimientos normalizados, errores) para filas con cuenta_id, tipo y monto."""
    preparados = []
    errores = []
    if len(movimientos) < 2:
        errores.append('Debe registrar al menos 2 movimientos por asiento.')

    for i, movimiento in enumerate(movimientos, start=1):
        cuenta_id = str(movimiento.get('cuenta_id', '')).strip()
        tipo = str(movimiento.get('tipo', '')).strip()
        monto_str = str(movimiento.get('monto', '')).strip()
        if not cuenta_id or not tipo or not monto_str:
            errores.append(f'Línea {i}: Todos los campos son obligatorios.')
            continue
        try:
            monto = Decimal(monto_str)
            if not monto.is_finite():
                raise InvalidOperation
            if monto <= 0:
                errores.append(f'Línea {i}: El monto debe ser mayor a 0.')
                continue
            # Evitar que el guardado redondee un asiento previamente validado.
            if monto >= Decimal('10000000000') or monto != monto.quantize(Decimal('0.01')):
                errores.append(f'Línea {i}: El monto debe tener como máximo 10 enteros y 2 decimales.')
                continue
        except (InvalidOperation, ValueError):
            errores.append(f'Línea {i}: El monto ingresado no es válido.')
            continue
        if tipo not in ('debe', 'haber'):
            errores.append(f'Línea {i}: El tipo debe ser Debe o Haber.')
            continue
        try:
            cuenta = CuentaContable.objects.get(id=int(cuenta_id))
        except (CuentaContable.DoesNotExist, ValueError, OverflowError):
            errores.append(f'Línea {i}: La cuenta seleccionada no existe.')
            continue
        preparados.append({'cuenta': cuenta, 'tipo': tipo, 'monto': monto})

    if not errores:
        debe = sum((m['monto'] for m in preparados if m['tipo'] == 'debe'), Decimal('0'))
        haber = sum((m['monto'] for m in preparados if m['tipo'] == 'haber'), Decimal('0'))
        if debe != haber:
            errores.append(
                f'El asiento no está balanceado. Debe: S/ {debe:,.2f} ≠ Haber: S/ {haber:,.2f}'
            )
    return preparados, errores


def validar_asiento_formulario(datos):
    """Adapta los campos del formulario existente a la validación compartida."""
    try:
        cantidad = int(datos.get('num_movimientos', 0))
    except (TypeError, ValueError):
        return [], ['El número de movimientos no es válido.']
    if cantidad > 1000:
        return [], ['El asiento no puede superar los 1000 movimientos.']
    movimientos = [
        {
            'cuenta_id': datos.get(f'cuenta_{i}', ''),
            'tipo': datos.get(f'tipo_{i}', ''),
            'monto': datos.get(f'monto_{i}', ''),
        }
        for i in range(cantidad)
    ]
    preparados, errores = validar_movimientos(movimientos)
    fecha = datos.get('fecha', '').strip()
    if not fecha:
        errores.append('La fecha es obligatoria.')
    else:
        try:
            validar_fecha(fecha)
        except ValueError:
            errores.append('La fecha no es válida.')
    return preparados, errores
