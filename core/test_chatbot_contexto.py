import json
from decimal import Decimal
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from core.models import AsientoContable, CuentaContable, Movimiento
from core.services.chatbot import generar_propuesta
from core.services.contexto_contable import construir_contexto, resolver_periodo


class ContextoContableTests(TestCase):
    def setUp(self):
        self.cuentas = {}
        for codigo, nombre, tipo, subcategoria in [
            ('CAJ', 'Efectivo y bancos', 'activo', ''),
            ('MER', 'Mercaderías', 'activo', 'existencias'),
            ('CLI', 'Cuentas por cobrar', 'activo', ''),
            ('PRO', 'Cuentas por pagar', 'pasivo', ''),
            ('VEN', 'Ventas', 'ingreso', ''),
            ('GAS', 'Gastos operativos', 'gasto', 'gasto_operativo'),
            ('COS', 'Costo de ventas', 'gasto', 'costo_ventas'),
            ('CAP', 'Capital', 'patrimonio', ''),
        ]:
            self.cuentas[codigo] = CuentaContable.objects.create(
                codigo=codigo, nombre=nombre, tipo=tipo, subcategoria=subcategoria)
        self.proveedor = Mock()
        self.proveedor.completar.return_value = json.dumps(self.propuesta())
        self.hecho = 'En el inventario se observa un saldo final de S/ 10,000 al cierre del mes'

    def asiento(self, fecha, descripcion, debe, haber, monto):
        a = AsientoContable.objects.create(fecha=fecha, descripcion=descripcion)
        for codigo, tipo in [(debe, 'debe'), (haber, 'haber')]:
            Movimiento.objects.create(asiento=a, cuenta=self.cuentas[codigo], tipo=tipo, monto=monto)
        return a

    def ejercicio(self):
        self.asiento('2020-07-08', 'Aporte de capital', 'CAJ', 'CAP', '100000')
        self.asiento('2020-07-20', 'Compra de mercadería', 'MER', 'CAJ', '50000')
        self.asiento('2020-07-25', 'Venta al crédito', 'CLI', 'VEN', '70000')
        self.asiento('2020-07-31', 'Pago de gastos operativos', 'GAS', 'CAJ', '20000')

    def contexto(self, hecho='inventario', fecha='2020-07-31'):
        return construir_contexto(hecho, list(CuentaContable.objects.all()), fecha)

    def propuesta(self, monto='40000.00'):
        return {'estado': 'propuesta', 'fecha': '2026-01-01', 'descripcion': 'Costo de ventas',
                'movimientos': [{'cuenta_codigo': 'COS', 'tipo': 'debe', 'monto': monto},
                                {'cuenta_codigo': 'MER', 'tipo': 'haber', 'monto': monto}]}

    def generar(self, hecho=None):
        return generar_propuesta(hecho or self.hecho, self.proveedor)

    def test_varios_asientos_relacionados_con_fecha_y_contrapartidas(self):
        self.ejercicio()
        ctx = self.contexto()
        self.assertEqual(len(ctx['asientos']), 3)
        compra = next(a for a in ctx['asientos'] if a['descripcion'].startswith('Compra'))
        self.assertEqual(compra['fecha'], '2020-07-20')
        self.assertEqual({m['cuenta_codigo'] for m in compra['movimientos']}, {'CAJ', 'MER'})

    def test_saldo_acumulado_y_naturaleza(self):
        self.ejercicio()
        saldos = {s['cuenta_codigo']: s for s in self.contexto('efectivo capital')['saldos']}
        self.assertEqual(saldos['CAJ']['total_debe'], '100000.00')
        self.assertEqual(saldos['CAJ']['total_haber'], '70000.00')
        self.assertEqual(saldos['CAJ']['saldo_debe_menos_haber'], '30000.00')
        self.assertEqual(saldos['CAP']['saldo_segun_naturaleza'], '100000.00')

    def test_inventario_compras_final_y_diferencia_variables(self):
        for compra, final in [('50000', '10000'), ('87654.32', '12345.67')]:
            with self.subTest(compra=compra):
                AsientoContable.objects.all().delete()
                self.asiento('2020-07-20', 'Compra', 'MER', 'CAJ', compra)
                d = self.contexto(f'Inventario final S/ {final}')['datos_detectados']
                self.assertEqual(Decimal(d['inventario_compras_periodo']), Decimal(compra))
                self.assertEqual(Decimal(d['diferencia']), Decimal(compra) - Decimal(final))

    def test_saldo_inicial_y_salidas_no_solo_compras(self):
        self.asiento('2020-06-01', 'Aporte de inventario', 'MER', 'CAP', '8000')
        self.asiento('2020-07-20', 'Compra', 'MER', 'CAJ', '50000')
        self.asiento('2020-07-25', 'Costo ya reconocido', 'COS', 'MER', '6000')
        ctx = self.contexto('Inventario final 10000')
        self.assertEqual(ctx['datos_detectados']['diferencia'], '42000.00')
        inv = next(s for s in ctx['saldos'] if s['cuenta_codigo'] == 'MER')
        self.assertEqual(inv['saldo_anterior_al_periodo'], '8000.00')
        self.assertEqual(inv['haber_periodo'], '6000.00')

    def test_corte_excluye_futuro(self):
        self.ejercicio()
        self.asiento('2020-08-01', 'Compra futura', 'MER', 'CAJ', '999')
        ctx = self.contexto('inventario final 10000')
        self.assertEqual(ctx['datos_detectados']['diferencia'], '40000.00')
        self.assertFalse(any(a['fecha'] > '2020-07-31' for a in ctx['asientos']))

    def test_periodo_unico_desde_asientos(self):
        self.ejercicio()
        self.assertEqual(resolver_periodo(self.hecho, None), ('2020-07-31', None))

    def test_periodo_ambiguo_no_elige_ultimo(self):
        self.ejercicio()
        self.asiento('2021-07-01', 'Compra', 'MER', 'CAJ', '500')
        r = self.generar()
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertIn('periodo', r['datos_faltantes'])
        self.proveedor.completar.assert_not_called()

    def test_mes_explicito_y_bisiesto(self):
        self.assertEqual(resolver_periodo('Inventario al cierre de febrero de 2020', None), ('2020-02-29', None))

    def test_sin_movimientos_no_inventa_saldo_cero(self):
        ctx = self.contexto('inventario final 10000')
        self.assertTrue(all(s['saldo_debe_menos_haber'] is None for s in ctx['saldos']))
        self.assertNotIn('diferencia', ctx['datos_detectados'])
        r = self.generar('31/07/2020 Inventario final 10000; registrar como costo de ventas')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.proveedor.completar.assert_not_called()

    def test_sin_asientos_no_inventa_periodo(self):
        self.assertIn('periodo', self.generar()['datos_faltantes'])

    def test_multiples_conceptos_seleccionan_cuentas(self):
        ctx = self.contexto('efectivo, cuentas por cobrar, cuentas por pagar, ventas, gastos, capital e inventario')
        self.assertEqual({s['cuenta_codigo'] for s in ctx['saldos']}, set(self.cuentas))

    def test_cuenta_mencionada_por_nombre_o_codigo(self):
        c = CuentaContable.objects.create(codigo='ABC', nombre='Anticipos especiales', tipo='activo')
        for hecho in ['Revisar ABC', 'Anticipos especiales']:
            self.assertIn(c.codigo, {s['cuenta_codigo'] for s in self.contexto(hecho)['saldos']})

    def test_fechas_e_importes_no_son_codigos_de_cuenta(self):
        CuentaContable.objects.create(codigo='25', nombre='Materiales auxiliares', tipo='activo')
        self.assertEqual(self.contexto('25/07/2020 Operación por 25 soles')['saldos'], [])
        self.assertEqual(self.contexto('cuenta 25')['saldos'][0]['cuenta_codigo'], '25')

    def test_catalogo_grande_se_acota_priorizando_cuentas_relacionadas(self):
        CuentaContable.objects.bulk_create([CuentaContable(codigo=f'A{i:03}', nombre=f'Otra {i}', tipo='activo')
                                            for i in range(220)])
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Cuál es el importe?'})
        self.generar('31/07/2020 Compra de mercaderías al contado')
        mensaje = self.proveedor.completar.call_args.args[0][0]['content']
        catalogo = json.loads(mensaje.split('CATÁLOGO COMPLETO:\n')[1].split('\nFECHA DETECTADA:')[0])
        self.assertEqual(len(catalogo), 200)
        self.assertTrue({'MER', 'CAJ'} <= {c['codigo'] for c in catalogo})

    def test_cobro_del_saldo_anterior_genera_propuesta(self):
        self.ejercicio()

        def completar(mensajes):
            ctx = json.loads(mensajes[0]['content'].split('CONTEXTO DE SALDOS: ')[1])
            saldo = next(s['saldo_debe_menos_haber'] for s in ctx['saldos'] if s['cuenta_codigo'] == 'CLI')
            return json.dumps({'estado': 'propuesta', 'fecha': '2020-07-31', 'descripcion': 'Cobro total',
                               'movimientos': [{'cuenta_codigo': 'CAJ', 'tipo': 'debe', 'monto': saldo},
                                               {'cuenta_codigo': 'CLI', 'tipo': 'haber', 'monto': saldo}]})

        self.proveedor.completar.side_effect = completar
        r = self.generar('31/07/2020 Se cobra en efectivo todo el saldo registrado de cuentas por cobrar')
        self.assertEqual(r['estado'], 'propuesta')
        self.assertEqual(r['movimientos'][0]['monto'], '70000.00')
        self.assertEqual(AsientoContable.objects.count(), 4)

    def test_multiples_inventarios_requieren_atribucion(self):
        self.ejercicio()
        CuentaContable.objects.create(codigo='INV2', nombre='Mercaderías almacén 2', tipo='activo')
        self.assertEqual(self.generar()['datos_faltantes'], ['cuenta_inventario'])

    def test_diferencia_no_prueba_tratamiento(self):
        self.ejercicio()
        r = self.generar()
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertEqual(r['datos_detectados']['diferencia'], '40000.00')
        self.assertTrue({'pregunta', 'motivo', 'datos_detectados', 'datos_faltantes'} <= r.keys())
        self.proveedor.completar.assert_not_called()

    def test_propuesta_utiliza_contexto_db_sin_escribir(self):
        self.ejercicio()

        def completar(mensajes):
            ctx = json.loads(mensajes[0]['content'].split('CONTEXTO DE SALDOS: ')[1])
            self.assertEqual(ctx['periodo'], '2020-07')
            return json.dumps(self.propuesta(ctx['datos_detectados']['diferencia']))

        self.proveedor.completar.side_effect = completar
        r = self.generar(self.hecho + '; registrar la diferencia como costo de ventas')
        self.assertEqual(r['estado'], 'propuesta')
        self.assertEqual(r['fecha'], '2020-07-31')
        self.assertEqual(r['movimientos'][0]['monto'], '40000.00')
        self.assertEqual(AsientoContable.objects.count(), 4)
        self.assertEqual(Movimiento.objects.count(), 8)

    def test_proveedor_no_puede_inventar_diferencia_aunque_cuadre(self):
        self.ejercicio()
        self.proveedor.completar.return_value = json.dumps(self.propuesta('99999.00'))
        r = self.generar(self.hecho + '; registrar como costo de ventas')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertIn('ajuste_coherente_con_saldo_registrado', r['datos_faltantes'])

    def test_no_interpreta_negacion_como_tratamiento_confirmado(self):
        self.ejercicio()
        r = self.generar(self.hecho + '; no registrar como costo de ventas')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.proveedor.completar.assert_not_called()

    def test_limites_no_recortan_agregados(self):
        for _ in range(25):
            self.asiento('2020-07-20', 'Compra', 'MER', 'CAJ', '1000')
        ctx = self.contexto('inventario final 1000')
        self.assertEqual(len(ctx['asientos']), 20)
        self.assertTrue(ctx['detalle_truncado'])
        self.assertEqual(ctx['datos_detectados']['inventario_saldo_registrado'], '25000.00')

    def test_limite_lineas_por_asiento(self):
        a = self.asiento('2020-07-20', 'Compra', 'MER', 'CAJ', '1')
        Movimiento.objects.bulk_create([Movimiento(asiento=a, cuenta=self.cuentas['MER'], tipo='debe', monto='1')
                                        for _ in range(105)])
        ctx = self.contexto()
        self.assertEqual(sum(len(a['movimientos']) for a in ctx['asientos']), 100)
        self.assertTrue(ctx['detalle_truncado'])

    def test_limite_cuentas_impide_diferencia_parcial(self):
        self.ejercicio()
        CuentaContable.objects.bulk_create([CuentaContable(codigo=f'INV{i}', nombre=f'Inventario {i}', tipo='activo')
                                            for i in range(55)])
        ctx = self.contexto(self.hecho)
        self.assertEqual(len(ctx['saldos']), 50)
        self.assertTrue(ctx['cuentas_truncadas'])
        self.assertEqual(self.generar()['estado'], 'requiere_aclaracion')

    def test_api_revision_y_confirmacion_explicita(self):
        self.ejercicio()
        with patch('core.services.chatbot.ProveedorGroq', return_value=self.proveedor):
            r = self.client.post(reverse('chatbot_api'), {'message': self.hecho + '; registrar como costo de ventas'}).json()
        self.assertEqual(r['estado'], 'propuesta')
        self.assertEqual(AsientoContable.objects.count(), 4)
        pagina = self.client.get(r['revision_url'])
        self.assertEqual(pagina.context['formulario_inicial']['fecha'], '2020-07-31')
        self.assertEqual(AsientoContable.objects.count(), 4)
        guardado = self.client.post(r['revision_url'], {
            'fecha': r['fecha'], 'descripcion': r['descripcion'], 'num_movimientos': '2',
            'cuenta_0': self.cuentas['COS'].pk, 'tipo_0': 'debe', 'monto_0': '40000',
            'cuenta_1': self.cuentas['MER'].pk, 'tipo_1': 'haber', 'monto_1': '40000'})
        self.assertEqual(guardado.status_code, 302)
        self.assertEqual(AsientoContable.objects.count(), 5)
