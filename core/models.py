"""
Modelos del Sistema Contable.

Define tres entidades principales:
- CuentaContable: Catálogo de cuentas con su clasificación (Activo, Pasivo, etc.)
- AsientoContable: Cabecera de cada asiento con fecha y descripción
- Movimiento: Líneas de detalle (Debe/Haber) vinculadas a un asiento y una cuenta
"""
from django.db import models
from decimal import Decimal


class CuentaContable(models.Model):
    """
    Representa una cuenta del plan contable.
    Cada cuenta tiene un código único, nombre y tipo que determina
    su comportamiento en los reportes financieros.
    """
    TIPO_CHOICES = [
        ('activo', 'Activo'),
        ('pasivo', 'Pasivo'),
        ('patrimonio', 'Patrimonio'),
        ('ingreso', 'Ingreso'),
        ('gasto', 'Gasto'),
    ]

    # Subcategoría para clasificar cuentas en el Estado de Resultados
    SUBCATEGORIA_CHOICES = [
        ('', 'General'),
        ('costo_ventas', 'Costo de Ventas'),
        ('gasto_operativo', 'Gasto Operativo'),
        ('gasto_financiero', 'Gasto Financiero'),
        ('otro_ingreso', 'Otro Ingreso'),
        ('otro_gasto', 'Otro Gasto'),
    ]

    codigo = models.CharField(max_length=20, unique=True, verbose_name='Código')
    nombre = models.CharField(max_length=200, verbose_name='Nombre')
    tipo = models.CharField(max_length=20, choices=TIPO_CHOICES, verbose_name='Tipo')
    subcategoria = models.CharField(
        max_length=20,
        choices=SUBCATEGORIA_CHOICES,
        blank=True,
        default='',
        verbose_name='Subcategoría (EE.RR.)'
    )

    class Meta:
        ordering = ['codigo']
        verbose_name = 'Cuenta Contable'
        verbose_name_plural = 'Cuentas Contables'

    def __str__(self):
        return f"{self.codigo} - {self.nombre}"

    @property
    def naturaleza_deudora(self):
        """Las cuentas de Activo y Gasto tienen naturaleza deudora."""
        return self.tipo in ('activo', 'gasto')


class AsientoContable(models.Model):
    """
    Cabecera de un asiento contable.
    Agrupa uno o más movimientos que deben estar balanceados (Debe == Haber).
    """
    fecha = models.DateField(verbose_name='Fecha')
    descripcion = models.TextField(blank=True, default='', verbose_name='Descripción')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha', 'id'] 
        verbose_name = 'Asiento Contable'
        verbose_name_plural = 'Asientos Contables'

    def __str__(self):
        return f"Asiento #{self.id} — {self.fecha}"

    @property
    def total_debe(self):
        """Suma total de movimientos al Debe."""
        return self.movimientos.filter(tipo='debe').aggregate(
            total=models.Sum('monto'))['total'] or Decimal('0')

    @property
    def total_haber(self):
        """Suma total de movimientos al Haber."""
        return self.movimientos.filter(tipo='haber').aggregate(
            total=models.Sum('monto'))['total'] or Decimal('0')

    @property
    def esta_balanceado(self):
        """Verifica que el asiento esté cuadrado."""
        return self.total_debe == self.total_haber


class Movimiento(models.Model):
    """
    Línea de detalle de un asiento contable.
    Cada movimiento afecta una cuenta específica al Debe o al Haber.
    """
    TIPO_CHOICES = [
        ('debe', 'Debe'),
        ('haber', 'Haber'),
    ]

    asiento = models.ForeignKey(
        AsientoContable,
        on_delete=models.CASCADE,
        related_name='movimientos',
        verbose_name='Asiento'
    )
    cuenta = models.ForeignKey(
        CuentaContable,
        on_delete=models.PROTECT,
        related_name='movimientos',
        verbose_name='Cuenta'
    )
    tipo = models.CharField(max_length=5, choices=TIPO_CHOICES, verbose_name='Tipo')
    monto = models.DecimalField(max_digits=12, decimal_places=2, verbose_name='Monto')

    class Meta:
        verbose_name = 'Movimiento'
        verbose_name_plural = 'Movimientos'

    def __str__(self):
        return f"{self.cuenta} — {self.get_tipo_display()}: S/ {self.monto:,.2f}"