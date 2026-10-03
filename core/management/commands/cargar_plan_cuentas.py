"""Carga aditiva e idempotente del catálogo, sin tocar asientos ni movimientos."""
from django.core.management.base import BaseCommand
from django.db import transaction

from core.models import CuentaContable
from core.plan_cuentas import PLAN_CUENTAS


class Command(BaseCommand):
    help = 'Carga el plan de cuentas de clase sin eliminar datos existentes.'

    def handle(self, *args, **options):
        creadas = actualizadas = sin_cambios = 0
        avisos = []
        with transaction.atomic():
            for codigo, nombre, tipo, subcategoria in PLAN_CUENTAS:
                cuenta, creada = CuentaContable.objects.get_or_create(
                    codigo=codigo,
                    defaults={'nombre': nombre, 'tipo': tipo, 'subcategoria': subcategoria},
                )
                if creada:
                    creadas += 1
                    continue

                cuenta = CuentaContable.objects.select_for_update().get(pk=cuenta.pk)
                campos = []
                if cuenta.nombre != nombre:
                    cuenta.nombre = nombre
                    campos.append('nombre')

                tiene_movimientos = cuenta.movimientos.exists()
                for campo, esperado in (('tipo', tipo), ('subcategoria', subcategoria)):
                    if getattr(cuenta, campo) == esperado:
                        continue
                    if tiene_movimientos:
                        avisos.append(
                            f'{codigo}: se conserva {campo}={getattr(cuenta, campo)!r}; '
                            f'el catálogo propone {esperado!r}. Tiene movimientos; revisar manualmente.'
                        )
                    else:
                        setattr(cuenta, campo, esperado)
                        campos.append(campo)

                if campos:
                    cuenta.save(update_fields=campos)
                    actualizadas += 1
                else:
                    sin_cambios += 1

        for aviso in avisos:
            self.stderr.write(self.style.WARNING(aviso))
        self.stdout.write(self.style.SUCCESS(
            f'Catálogo: {len(PLAN_CUENTAS)} cuentas. Creadas: {creadas}. '
            f'Actualizadas: {actualizadas}. Sin cambios: {sin_cambios}. '
            f'Total registrado: {CuentaContable.objects.count()}.'
        ))
