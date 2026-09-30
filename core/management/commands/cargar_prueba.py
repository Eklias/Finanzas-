"""
Comando de gestión para cargar datos de prueba.

Simula las operaciones de la empresa "AMD Tech Perú S.A.C." con las
siguientes transacciones de octubre 2026:

1. Capital inicial: S/ 80,000 (50,000 efectivo + 30,000 equipos)
2. Compra de mercadería al crédito: S/ 25,000
3. Venta al contado: S/ 18,000
4. Costo de venta: S/ 11,000
5. Venta al crédito: S/ 22,000
6. Costo de venta: S/ 13,000
7. Gastos administrativos: S/ 3,000

Uso:
    python manage.py cargar_prueba
"""
from django.core.management.base import BaseCommand
from core.models import CuentaContable, AsientoContable, Movimiento
from decimal import Decimal
from datetime import date


class Command(BaseCommand):
    help = 'Carga datos de prueba: empresa AMD Tech Perú S.A.C.'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING('Eliminando datos existentes...'))
        Movimiento.objects.all().delete()
        AsientoContable.objects.all().delete()
        CuentaContable.objects.all().delete()

        self.stdout.write(self.style.SUCCESS('Creando catalogo de cuentas...'))

        # --- CATALOGO DE CUENTAS ---
        # (codigo, nombre, tipo, subcategoria)
        cuentas_data = [
            # Activos
            ('10', 'Efectivo y Equivalentes de Efectivo', 'activo', ''),
            ('12', 'Cuentas por Cobrar Comerciales', 'activo', ''),
            ('20', 'Mercaderias', 'activo', ''),
            ('33', 'Propiedad, Planta y Equipo', 'activo', ''),
            # Pasivos
            ('42', 'Cuentas por Pagar Comerciales', 'pasivo', ''),
            # Patrimonio
            ('50', 'Capital Social', 'patrimonio', ''),
            # Ingresos
            ('70', 'Ventas', 'ingreso', ''),
            # Gastos
            ('69', 'Costo de Ventas', 'gasto', 'costo_ventas'),
            ('94', 'Gastos Administrativos', 'gasto', 'gasto_operativo'),
        ]

        cuentas = {}
        for codigo, nombre, tipo, subcategoria in cuentas_data:
            cuenta = CuentaContable.objects.create(
                codigo=codigo, nombre=nombre, tipo=tipo, subcategoria=subcategoria
            )
            cuentas[codigo] = cuenta
            self.stdout.write(f'  [OK] {cuenta}')

        self.stdout.write(self.style.SUCCESS('\nRegistrando asientos contables...'))

        # --- ASIENTO 1: Capital inicial ---
        a1 = AsientoContable.objects.create(
            fecha=date(2026, 10, 1),
            descripcion='Apertura de empresa con aporte de capital: S/ 50,000 en efectivo y S/ 30,000 en equipos'
        )
        Movimiento.objects.create(asiento=a1, cuenta=cuentas['10'], tipo='debe', monto=Decimal('50000'))
        Movimiento.objects.create(asiento=a1, cuenta=cuentas['33'], tipo='debe', monto=Decimal('30000'))
        Movimiento.objects.create(asiento=a1, cuenta=cuentas['50'], tipo='haber', monto=Decimal('80000'))
        self.stdout.write(f'  [OK] {a1}')

        # --- ASIENTO 2: Compra de mercaderia al credito ---
        a2 = AsientoContable.objects.create(
            fecha=date(2026, 10, 5),
            descripcion='Compra de mercaderia al credito por S/ 25,000'
        )
        Movimiento.objects.create(asiento=a2, cuenta=cuentas['20'], tipo='debe', monto=Decimal('25000'))
        Movimiento.objects.create(asiento=a2, cuenta=cuentas['42'], tipo='haber', monto=Decimal('25000'))
        self.stdout.write(f'  [OK] {a2}')

        # --- ASIENTO 3: Venta al contado ---
        a3 = AsientoContable.objects.create(
            fecha=date(2026, 10, 10),
            descripcion='Venta de mercaderia al contado por S/ 18,000'
        )
        Movimiento.objects.create(asiento=a3, cuenta=cuentas['10'], tipo='debe', monto=Decimal('18000'))
        Movimiento.objects.create(asiento=a3, cuenta=cuentas['70'], tipo='haber', monto=Decimal('18000'))
        self.stdout.write(f'  [OK] {a3}')

        # --- ASIENTO 4: Costo de venta ---
        a4 = AsientoContable.objects.create(
            fecha=date(2026, 10, 10),
            descripcion='Reconocimiento del costo de venta por S/ 11,000'
        )
        Movimiento.objects.create(asiento=a4, cuenta=cuentas['69'], tipo='debe', monto=Decimal('11000'))
        Movimiento.objects.create(asiento=a4, cuenta=cuentas['20'], tipo='haber', monto=Decimal('11000'))
        self.stdout.write(f'  [OK] {a4}')

        # --- ASIENTO 5: Venta al credito ---
        a5 = AsientoContable.objects.create(
            fecha=date(2026, 10, 18),
            descripcion='Venta de mercaderia al credito por S/ 22,000'
        )
        Movimiento.objects.create(asiento=a5, cuenta=cuentas['12'], tipo='debe', monto=Decimal('22000'))
        Movimiento.objects.create(asiento=a5, cuenta=cuentas['70'], tipo='haber', monto=Decimal('22000'))
        self.stdout.write(f'  [OK] {a5}')

        # --- ASIENTO 6: Costo de venta ---
        a6 = AsientoContable.objects.create(
            fecha=date(2026, 10, 18),
            descripcion='Reconocimiento del costo de venta por S/ 13,000'
        )
        Movimiento.objects.create(asiento=a6, cuenta=cuentas['69'], tipo='debe', monto=Decimal('13000'))
        Movimiento.objects.create(asiento=a6, cuenta=cuentas['20'], tipo='haber', monto=Decimal('13000'))
        self.stdout.write(f'  [OK] {a6}')

        # --- ASIENTO 7: Gastos administrativos ---
        a7 = AsientoContable.objects.create(
            fecha=date(2026, 10, 25),
            descripcion='Pago de gastos administrativos por S/ 3,000'
        )
        Movimiento.objects.create(asiento=a7, cuenta=cuentas['94'], tipo='debe', monto=Decimal('3000'))
        Movimiento.objects.create(asiento=a7, cuenta=cuentas['10'], tipo='haber', monto=Decimal('3000'))
        self.stdout.write(f'  [OK] {a7}')

        # --- RESUMEN ---
        self.stdout.write(self.style.SUCCESS(
            f'\n=== DATOS CARGADOS EXITOSAMENTE ===\n'
            f'  Empresa: AMD Tech Peru S.A.C.\n'
            f'  Cuentas creadas: {CuentaContable.objects.count()}\n'
            f'  Asientos registrados: {AsientoContable.objects.count()}\n'
            f'  Movimientos creados: {Movimiento.objects.count()}\n'
        ))
#a