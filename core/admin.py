"""
Registro en el panel de administración de Django.
Permite gestionar los modelos desde /admin/.
"""
from django.contrib import admin
from .models import CuentaContable, AsientoContable, Movimiento


class MovimientoInline(admin.TabularInline):
    """Muestra los movimientos dentro del formulario de asiento."""
    model = Movimiento
    extra = 2


@admin.register(CuentaContable)
class CuentaContableAdmin(admin.ModelAdmin):
    list_display = ['codigo', 'nombre', 'tipo']
    list_filter = ['tipo']
    search_fields = ['codigo', 'nombre']


@admin.register(AsientoContable)
class AsientoContableAdmin(admin.ModelAdmin):
    list_display = ['id', 'fecha', 'descripcion']
    list_filter = ['fecha']
    inlines = [MovimientoInline]


@admin.register(Movimiento)
class MovimientoAdmin(admin.ModelAdmin):
    list_display = ['asiento', 'cuenta', 'tipo', 'monto']
    list_filter = ['tipo', 'cuenta']
#a