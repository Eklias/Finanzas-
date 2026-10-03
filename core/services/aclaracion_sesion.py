"""Una aclaración temporal por sesión, sin historial de conversaciones."""
import json
import re
import time

from .aclaraciones_contables import detectar_datos
from .contexto_contable import normalizar, grupos_cuenta
from .fechas import interpretar_fecha
from .resolver_aclaraciones import resolver_opciones, adaptar_opcion, presentar_opciones

CLAVE_ACLARACION = 'chatbot_aclaracion_pendiente'
CADUCIDAD = 1800


def consulta_opciones(mensaje):
    """Reconoce consultas, antes de intentar interpretar una elección o un hecho."""
    texto = normalizar(mensaje).strip(' ¿?¡!.')
    return bool(re.search(
        r'\b(?:que|cuales|cuantos)\b.*\b(?:inventarios?|existencias|opciones|cuentas|gastos?|pagos?)\b'
        r'|\b(?:muestrame|mostrar|dime|lista|listar|ver)\b.*\b(?:opciones|cuentas|inventarios?|existencias|gastos?|pagos?)\b',
        texto))


def tema_opciones(pendiente, mensaje=''):
    texto = normalizar(mensaje)
    campos = ' '.join(pendiente['datos_faltantes'])
    for tema, patron in [('inventario', r'inventari|existencias'),
                         ('gasto', r'gasto'), ('forma_pago', r'pago')]:
        if re.search(patron, texto):
            return tema
    for tema, patron in [('inventario', r'inventari|existencias'),
                         ('gasto', r'gasto'), ('forma_pago', r'forma_pago')]:
        if re.search(patron, campos):
            return tema
    return 'cuenta'


def opciones_cuenta(pendiente, cuentas, tema=None):
    """Filtra registros actuales por su clasificación y sus nombres reales."""
    tema = tema or tema_opciones(pendiente)
    if tema == 'inventario':
        return [c for c in cuentas if c.tipo == 'activo' and (
            'inventario' in grupos_cuenta(c)
            or 'mantenidos para la venta' in normalizar(c.nombre))]
    if tema == 'gasto':
        return [c for c in cuentas if c.tipo == 'gasto']
    if tema == 'forma_pago' or 'contrapartida' in pendiente['datos_faltantes']:
        return [c for c in cuentas if c.tipo == 'activo' and re.search(
            r'\b(?:efectivo|caja|bancos?)\b', normalizar(c.nombre))]
    opciones = [c for c in cuentas if re.search(
        r'(?<!\w)' + re.escape(c.codigo) + r'(?!\w)', pendiente['pregunta_pendiente'])]
    return opciones or cuentas


def operacion(texto):
    texto = normalizar(texto)
    for patron, nombre in [(r'\b(?:compra|compran|compraron)\b', 'compra'),
                           (r'\b(?:venta|vende|venden|vendieron)\b', 'venta'),
                           (r'\b(?:paga|pagan|pago|pagaron)\b.*\bgastos?\b', 'pago de gasto'),
                           (r'\b(?:paga|pagan|pago|pagaron|pague|pagamos)\b', 'pago'),
                           (r'\baporte\b', 'aporte')]:
        if re.search(patron, texto):
            return nombre
    return None


def nuevo_hecho_completo(mensaje, cuentas):
    fecha, duda = interpretar_fecha(mensaje)
    datos = detectar_datos(mensaje, cuentas, fecha)
    return bool(fecha and not duda and datos.get('importe') and operacion(mensaje))


def obtener_pendiente(sesion):
    pendiente = sesion.get(CLAVE_ACLARACION)
    if pendiente and time.time() - pendiente['actualizada_en'] > CADUCIDAD:
        sesion.pop(CLAVE_ACLARACION, None)
        return None
    return pendiente


def construir_opciones(pendiente, cuentas):
    """Opciones de la pregunta actual y cuentas vigentes, para cualquier campo."""
    campo = pendiente.get('campo_pendiente') or pendiente['datos_faltantes'][0]
    pregunta = pendiente['pregunta_pendiente']
    if 'opciones' in pendiente or 'opciones_validas' in pendiente:
        vigentes = {c.codigo: c for c in cuentas}
        opciones = []
        for opcion in pendiente.get('opciones', pendiente.get('opciones_validas', [])):
            opcion = adaptar_opcion(opcion)
            valor = opcion['valor']
            if isinstance(valor, dict):
                cuenta = vigentes.get(valor.get('cuenta_codigo'))
                if cuenta:
                    opciones.append({**opcion, 'etiqueta': cuenta.nombre, 'label': cuenta.nombre,
                                     'valor': {'cuenta_codigo': cuenta.codigo, 'cuenta_nombre': cuenta.nombre}})
            else:
                if campo == 'forma_pago' and valor == 'al contado':
                    opcion['sinonimos'] = list(dict.fromkeys([
                        *opcion['sinonimos'], 'efectivo', 'en efectivo', 'al efectivo']))
                opciones.append(opcion)
        return opciones
    if campo == 'forma_pago':
        valores = [v for v in ['al contado', 'al crédito']
                   if palabras_pago(v) in normalizar(pregunta)] or ['al contado', 'al crédito']
    elif any(p in campo for p in ('cuenta', 'tipo_gasto', 'contrapartida')):
        explicitas = [c for c in cuentas if re.search(r'\(' + re.escape(c.codigo) + r'\)', pregunta)]
        nombradas = [c for c in cuentas if normalizar(c.nombre) in normalizar(pregunta)]
        return [{'id': c.codigo, 'etiqueta': c.nombre,
                 'valor': {'cuenta_codigo': c.codigo, 'cuenta_nombre': c.nombre}}
                for c in sorted(explicitas or nombradas or opciones_cuenta(pendiente, cuentas), key=lambda c: c.codigo)]
    else:
        # Alternativas expresadas en la pregunta, no causas inventadas por el resolver.
        clausula = pregunta.split('¿')[-1].strip(' ?')
        clausula = re.sub(r'^(?:corresponde|la operaci[oó]n corresponde|fue)\s+(?:al?\s+)?', '', clausula, flags=re.I)
        if ':' in clausula:
            clausula = clausula.split(':', 1)[1]
        valores = re.split(r'\s+[ou]\s+|,\s*', clausula) if re.search(r'\s+[ou]\s+', clausula) else []
        valores = [re.sub(r'^(?:a |al |una? |la |el )+', '', v.strip()) for v in valores]
    return [adaptar_opcion({'id': normalizar(v).replace(' ', '_'), 'label': v, 'valor': v,
                           'sinonimos': ['efectivo', 'en efectivo', 'al efectivo']
                           if campo == 'forma_pago' and v == 'al contado' else []})
            for v in valores if v]


def palabras_pago(valor):
    return normalizar(valor).split()[-1]


def guardar_pendiente(sesion, original, resultado, anterior=None, respuesta=None):
    datos = {**(anterior or {}).get('datos_detectados', {}), **resultado['datos_detectados']}
    if operacion(original):
        datos.setdefault('operacion', operacion(original))
    # El proveedor se valida con Decimal; el serializador de sesiones usa JSON puro.
    datos = json.loads(json.dumps(datos, default=str, ensure_ascii=False))
    contexto = dict((anterior or {}).get('contexto', {}))
    if anterior and respuesta:
        # Solo la última respuesta por dato pendiente; no una lista de mensajes.
        for campo in anterior['datos_faltantes'][:20]:
            if campo in datos and campo not in resultado['datos_faltantes']:
                contexto[campo] = respuesta[:2000]
        contexto = dict(list(contexto.items())[-20:])
    pendiente = {
        'mensaje_original': original, 'datos_detectados': datos,
        'datos_faltantes': resultado['datos_faltantes'], 'pregunta_pendiente': resultado['pregunta'],
        'contexto': contexto, 'actualizada_en': time.time(),
        'campo_pendiente': resultado['datos_faltantes'][0],
        'contexto_contable': {**(anterior or {}).get('contexto_contable', {}),
                             **resultado.get('contexto_contable', {}), 'datos_detectados': datos},
    }
    from core.models import CuentaContable
    pendiente['opciones_validas'] = resultado.get('opciones_validas', construir_opciones(pendiente, list(CuentaContable.objects.all())))
    pendiente['opciones_validas'] = [adaptar_opcion(o) for o in pendiente['opciones_validas']]
    pendiente['opciones'] = pendiente['opciones_validas']
    # Una única alternativa en una pregunta cerrada constituye una propuesta
    # explícita; una lista filtrada por ambigüedad no la constituye.
    if (len(pendiente['opciones']) == 1 and re.match(
            r'^¿(?:fue|confirmas|corresponde)\b', resultado['pregunta'], re.I)):
        pendiente['opcion_propuesta'] = pendiente['opciones'][0]['id']
    if 'opcion_propuesta' in resultado:
        pendiente['opcion_propuesta'] = resultado['opcion_propuesta']
    if pendiente['opciones']:
        # La numeración visible siempre corresponde al orden guardado.
        pregunta = resultado['pregunta'].split('\n')[0]
        for opcion in pendiente['opciones']:
            if not isinstance(opcion['valor'], dict):
                pregunta = pregunta.replace(' (' + opcion['id'] + ')', '')
        resultado['pregunta'] = pregunta + '\n' + presentar_opciones(pendiente['opciones'])
    pendiente['pregunta'] = pendiente['pregunta_pendiente'] = resultado['pregunta']
    sesion[CLAVE_ACLARACION] = pendiente


def resolver_respuesta(mensaje, pendiente, cuentas):
    datos = dict(pendiente['datos_detectados'])
    fecha, duda = interpretar_fecha(mensaje)
    # Una respuesta completa el dato solicitado; no sobrescribe datos confirmados.
    nuevos = detectar_datos(mensaje, cuentas, fecha)
    datos.update({k: v for k, v in nuevos.items() if k in pendiente['datos_faltantes'] and not datos.get(k)})
    texto = normalizar(mensaje).strip().strip('.')
    if pendiente['datos_faltantes'][0] == 'importe' and re.fullmatch(r'\d+(?:[.,]\d+)*', texto):
        datos.update(detectar_datos('por ' + mensaje, cuentas, None))
    campo = pendiente.get('campo_pendiente') or pendiente['datos_faltantes'][0]
    opciones = construir_opciones(pendiente, cuentas)
    anteriores = pendiente.get('opciones', pendiente.get('opciones_validas', []))
    catalogo_cambio = bool(anteriores) and [o['id'] for o in anteriores] != [o['id'] for o in opciones]
    cuenta_sin_opciones = not opciones and any(
        p in campo for p in ('cuenta', 'tipo_gasto', 'contrapartida'))
    # En una lista cerrada, solo el resolver puede completar el campo actual;
    # el detector de texto no debe convertir «contado o crédito» en una elección.
    if opciones:
        datos.pop(campo, None)
    estado, candidatas = resolver_opciones(mensaje, pendiente, opciones) if campo not in datos else ('resuelta', [])
    if catalogo_cambio:
        # Repetir la lista vigente antes de interpretar números: el usuario
        # respondió a la numeración anterior, que puede haber cambiado.
        datos.pop(campo, None)
        estado, candidatas = 'ambigua', []
    if estado == 'resuelta' and candidatas:
        datos[campo] = adaptar_opcion(candidatas[0])['valor']
        if campo == 'cuenta_inventario':
            datos['cuentas_inventario'] = [datos[campo]['cuenta_codigo']]
    if datos.get('forma_pago') == 'al crédito':
        datos.pop('contrapartida', None)
    seguimiento = {
        'mensaje_original': pendiente['mensaje_original'], 'datos_detectados': datos,
        'dato_pendiente': pendiente['datos_faltantes'],
        'pregunta_pendiente': pendiente['pregunta_pendiente'],
        'contexto': pendiente.get('contexto', {}), 'respuesta_nueva_usuario': mensaje,
        'campo_pendiente': campo, 'opciones_validas': opciones,
        'contexto_contable': pendiente.get('contexto_contable', {}),
    }
    if (estado != 'resuelta' and (opciones or catalogo_cambio or cuenta_sin_opciones or estado == 'negativa' or re.match(r'^(?:si|esa|ese)\b', texto))
            ):
        compatibles = candidatas or opciones
        detalle = presentar_opciones(compatibles)
        seguimiento['aclaracion_resolver'] = {
            'estado': 'requiere_aclaracion',
            'pregunta': ('¿Cuál alternativa corresponde?\n' if estado == 'negativa'
                         else 'Necesito precisar tu respuesta. ¿Cuál alternativa corresponde?\n') +
                        (detalle if detalle else pendiente['pregunta_pendiente']),
            'motivo': 'La respuesta no identifica una única alternativa válida.',
            'datos_detectados': datos, 'datos_faltantes': pendiente['datos_faltantes'],
            'opciones_validas': compatibles,
        }
        if catalogo_cambio or cuenta_sin_opciones:
            seguimiento['aclaracion_resolver']['pregunta'] = (
                'El catálogo cambió. Selecciona una de las cuentas vigentes:\n' + detalle
                if opciones else 'No quedan cuentas disponibles para esta aclaración. '
                'Revisa el catálogo o cancela la aclaración.')
        if estado != 'negativa' and not catalogo_cambio and pendiente.get('opcion_propuesta') in {o['id'] for o in compatibles}:
            seguimiento['aclaracion_resolver']['opcion_propuesta'] = pendiente['opcion_propuesta']
    hecho = (pendiente['mensaje_original'] + '\nDatos aclarados: ' + json.dumps(datos, ensure_ascii=False)
             + '\nRespuesta a la aclaración: ' + mensaje)
    return hecho, datos, seguimiento, duda
