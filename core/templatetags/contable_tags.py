"""
Template tags personalizados para el sistema contable.
Provee filtros para formatear montos y tipos de cuenta.
"""
from django import template
from decimal import Decimal

register = template.Library()


@register.filter
def formato_moneda(valor):
    """Formatea un valor decimal como moneda peruana: S/ 1,234.56"""
    if valor is None:
        return 'S/ 0.00'
    try:
        valor = Decimal(str(valor))
        return f'S/ {valor:,.2f}'
    except Exception:
        return f'S/ {valor}'


@register.filter
def tipo_badge(tipo):
    """Retorna la clase CSS para el badge según el tipo de cuenta."""
    clases = {
        'activo': 'badge-activo',
        'pasivo': 'badge-pasivo',
        'patrimonio': 'badge-patrimonio',
        'ingreso': 'badge-ingreso',
        'gasto': 'badge-gasto',
    }
    return clases.get(tipo, 'badge-default')


@register.filter
def abs_value(valor):
    """Retorna el valor absoluto."""
    try:
        return abs(Decimal(str(valor)))
    except Exception:
        return valor
#a