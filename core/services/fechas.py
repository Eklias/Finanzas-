"""Extracción determinista de fechas: el proveedor no decide ni inventa el día."""
import re
from datetime import date


MESES = {nombre: numero for numero, nombre in enumerate((
    'enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio',
    'agosto', 'septiembre', 'octubre', 'noviembre', 'diciembre'), 1)}
MESES['setiembre'] = 9
PATRON = re.compile(
    r'(?<!\w)(?:(?P<iso>\d{4}-\d{1,2}-\d{1,2})|'
    r'(?P<numerica>\d{1,2}[/-]\d{1,2}[/-]\d{4})|'
    r'(?P<dia>\d{1,2})\s+de\s+(?P<mes>[a-záéíóú]+)\s+de\s+(?P<anio>\d{4}))(?!\w)',
    re.IGNORECASE,
)


def aclaracion_fecha(pregunta, motivo, detectados=None):
    return {'estado': 'requiere_aclaracion', 'pregunta': pregunta, 'motivo': motivo,
            'datos_detectados': detectados or {}, 'datos_faltantes': ['fecha']}


def interpretar_fecha(texto):
    """Devuelve (fecha ISO o None, aclaración o None).

    Varias fechas solo se resuelven con una etiqueta explícita del hecho/asiento;
    las otras deben estar identificadas como fechas de referencia o vencimiento.
    """
    encontradas = []
    for match in PATRON.finditer(texto):
        try:
            if match['iso']:
                anio, mes, dia = map(int, match['iso'].split('-'))
            elif match['numerica']:
                dia, mes, anio = map(int, re.split('[/-]', match['numerica']))
            else:
                dia, mes, anio = int(match['dia']), MESES[match['mes'].lower()], int(match['anio'])
            valor = date(anio, mes, dia).isoformat()
        except (ValueError, KeyError):
            return None, aclaracion_fecha(
                f'La fecha «{match[0]}» no es válida. ¿Cuál es la fecha correcta?',
                'Fecha de calendario inválida.', {'fecha_texto': match[0]})
        prefijo = texto[max(0, match.start() - 70):match.start()]
        principal = bool(re.search(r'fecha\s+(?:del?\s+)?(?:asiento|hecho(?:\s+contable)?|operación)\s*[:=]?\s*$', prefijo, re.I))
        referencia = bool(re.search(r'(?:vencimiento|fecha\s+de\s+referencia)\s*[:=]?\s*$', prefijo, re.I))
        encontradas.append((valor, principal, referencia))
    distintas = {f[0] for f in encontradas}
    if len(distintas) == 1:
        if all(f[2] for f in encontradas):
            return None, aclaracion_fecha(
                'La fecha indicada es de referencia o vencimiento. ¿Cuál es la fecha del hecho contable?',
                'No se indicó la fecha de la operación.')
        return encontradas[0][0], None
    if len(distintas) > 1:
        principales = {f[0] for f in encontradas if f[1]}
        if len(principales) == 1 and all(f[1] or f[2] for f in encontradas):
            return principales.pop(), None
        return None, aclaracion_fecha(
            'Hay varias fechas. ¿Cuál corresponde al hecho contable que desea registrar?',
            'No se puede determinar la fecha del asiento con seguridad.',
            {'fechas': sorted(distintas)})
    return None, None
