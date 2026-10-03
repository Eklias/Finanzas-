"""Datos explícitos y aclaraciones contables que no requieren consultar una IA."""
import re
from decimal import Decimal

from .contexto_contable import aclaracion, normalizar


def detectar_datos(hecho, cuentas, fecha):
    texto = normalizar(hecho)
    datos = {'fecha': fecha} if fecha else {}
    # Exigir un marcador de importe para no interpretar fechas o códigos como dinero.
    numeros = re.findall(
        r'(?:\bs/\.?\s*|\bpor\s+(?:s/\.?\s*)?)(\d+(?:[.,]\d+)*)(?![\w/.,])', texto)
    importes = set()
    for numero in numeros:
        if re.fullmatch(r'\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+(?:\.\d{1,2})?', numero):
            importes.add(Decimal(numero.replace(',', '')))
    if len(importes) == 1:
        datos['importe'] = format(importes.pop(), '.2f')
    if re.search(r'\bsoles\b|\bs/\.?', texto):
        datos['moneda'] = 'PEN'
    if re.search(r'\bal credito\b', texto) and not re.search(r'\b(?:no|sin)\s+(?:pago\s+)?al credito\b', texto):
        datos['forma_pago'] = 'al crédito'
    if re.search(r'\b(?:al contado|en efectivo)\b', texto) and not re.search(
            r'\b(?:no|sin)\s+(?:pago\s+)?(?:al contado|en efectivo)\b|\bcredito\b', texto):
        datos['forma_pago'] = 'al contado'
        efectivo = [c for c in cuentas if c.tipo == 'activo' and re.match(
            r'(?:efectivo|caja|bancos?)\b', normalizar(c.nombre))]
        if len(efectivo) == 1 and re.search(r'\b(?:paga|pagan|pago|pagaron|pagado)\b', texto):
            cuenta = efectivo[0]
            datos['contrapartida'] = {
                'cuenta_codigo': cuenta.codigo, 'cuenta_nombre': cuenta.nombre, 'tipo': 'haber',
            }
            if 'importe' in datos:
                datos['contrapartida']['monto'] = datos['importe']
    return datos


def aclarar_gasto_operativo(hecho, cuentas, datos):
    texto = normalizar(hecho)
    if not re.search(r'\bgastos?\s+operativos?\b', texto):
        return None
    # Una especificación expresa puede ser evaluada por el proveedor. Una lista de
    # alternativas o una negación no resuelve la naturaleza del gasto.
    especificaciones = re.findall(
        r'\bgastos? de personal\b|\bservicios (?:prestados )?(?:por|de) terceros\b'
        r'|\btributos\b|\botros gastos de gestion\b', texto)
    if len(especificaciones) == 1 and not re.search(r'\b(?:no|sin|quizas)\b|[?¿]', texto):
        return None
    opciones = [c for c in cuentas if c.tipo == 'gasto' and re.search(
        r'\bpersonal\b|\bservicios\b.*\bterceros\b|\btributos\b|\botros gastos de gestion\b',
        normalizar(c.nombre))]
    opciones.sort(key=lambda c: c.codigo)
    pregunta = '¿Qué tipo de gasto operativo se pagó'
    if opciones:
        pregunta += ': ' + ', '.join(f'{c.nombre} ({c.codigo})' for c in opciones) + ' u otro'
    pregunta += '?'
    faltantes = ['tipo_gasto_operativo']
    for campo, consulta in [('fecha', '¿En qué fecha ocurrió?'),
                            ('importe', '¿Cuál fue el importe?'),
                            ('forma_pago', '¿Cuál fue la forma de pago?')]:
        if campo not in datos:
            faltantes.append(campo)
            pregunta += ' ' + consulta
    return aclaracion(
        pregunta,
        '“Gastos operativos” no especifica la naturaleza del gasto ni justifica una cuenta contable concreta.',
        datos, faltantes)
