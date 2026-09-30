import os
import django
from decimal import Decimal

# Configurar entorno Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'contabilidad.settings')
django.setup()

from django.utils import timezone
from core.models import CuentaContable, AsientoContable, Movimiento

def cargar_caso_completo():
    print("Iniciando carga de caso contable maestro...")
    hoy = timezone.now().date()
    
    # 1. Limpiar datos previos
    AsientoContable.objects.all().delete()
    CuentaContable.objects.all().delete()
    
    # 2. Crear Cuentas Estándar
    c10 = CuentaContable.objects.create(codigo='10', nombre='Efectivo y Equivalentes', tipo='activo')
    c20 = CuentaContable.objects.create(codigo='20', nombre='Mercaderías', tipo='activo')
    c42 = CuentaContable.objects.create(codigo='42', nombre='Cuentas por Pagar Comerciales', tipo='pasivo')
    c50 = CuentaContable.objects.create(codigo='50', nombre='Capital Social', tipo='patrimonio')
    c70 = CuentaContable.objects.create(codigo='70', nombre='Ventas', tipo='ingreso')
    c60 = CuentaContable.objects.create(codigo='60', nombre='Compras', tipo='gasto', subcategoria='costo_ventas')

    # 3. Registrar Asiento de Apertura (Capital)
    a1 = AsientoContable.objects.create(descripcion='Asiento de Apertura - Aporte de Capital', fecha=hoy)
    Movimiento.objects.create(asiento=a1, cuenta=c10, monto=Decimal('100000.00'), tipo='debe')
    Movimiento.objects.create(asiento=a1, cuenta=c50, monto=Decimal('100000.00'), tipo='haber')

    # 4. Compra de Mercaderías al crédito (60k)
    a2 = AsientoContable.objects.create(descripcion='Compra de Mercaderías al Crédito', fecha=hoy)
    Movimiento.objects.create(asiento=a2, cuenta=c20, monto=Decimal('60000.00'), tipo='debe')
    Movimiento.objects.create(asiento=a2, cuenta=c42, monto=Decimal('60000.00'), tipo='haber')
    
    # 5. Venta para generar utilidad de 10k
    a3 = AsientoContable.objects.create(descripcion='Venta de Mercaderías al Contado', fecha=hoy)
    Movimiento.objects.create(asiento=a3, cuenta=c10, monto=Decimal('50000.00'), tipo='debe')
    Movimiento.objects.create(asiento=a3, cuenta=c70, monto=Decimal('50000.00'), tipo='haber')
    
    # Costo de ventas (40k)
    a4 = AsientoContable.objects.create(descripcion='Costo de Ventas', fecha=hoy)
    Movimiento.objects.create(asiento=a4, cuenta=c60, monto=Decimal('40000.00'), tipo='debe')
    Movimiento.objects.create(asiento=a4, cuenta=c20, monto=Decimal('40000.00'), tipo='haber')

    # 6. Pago parcial de deuda (10k)
    a5 = AsientoContable.objects.create(descripcion='Pago Parcial a Proveedores', fecha=hoy)
    Movimiento.objects.create(asiento=a5, cuenta=c42, monto=Decimal('10000.00'), tipo='debe')
    Movimiento.objects.create(asiento=a5, cuenta=c10, monto=Decimal('10000.00'), tipo='haber')

    print("¡Caso cargado exitosamente!")
    print("Saldos Finales Esperados:")
    print("- Caja (10): 100k + 50k - 10k = 140,000 (ACTIVO)")
    print("- Mercaderías (20): 60k - 40k = 20,000 (ACTIVO)")
    print("- TOTAL ACTIVO: 160,000")
    print("- Cuentas por Pagar (42): 60k - 10k = 50,000 (PASIVO)")
    print("- Capital (50): 100,000 (PATRIMONIO)")
    print("- Utilidad (Venta 50k - Gasto 40k): 10,000 (PATRIMONIO)")
    print("- TOTAL PASIVO + PATRIMONIO: 160,000")

if __name__ == "__main__":
    cargar_caso_completo()
