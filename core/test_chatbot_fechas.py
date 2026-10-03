import json
from datetime import date
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from core.models import AsientoContable, CuentaContable, Movimiento
from core.services.chatbot import generar_propuesta, validar_propuesta, ErrorChatbot
from core.services.fechas import interpretar_fecha
from core.services.contexto_contable import construir_contexto


class FechasChatbotTests(TestCase):
    def setUp(self):
        # Códigos personalizados: la integración debe resolver el catálogo real.
        self.clientes = CuentaContable.objects.create(codigo='CLI', nombre='Clientes', tipo='activo')
        self.ventas = CuentaContable.objects.create(codigo='VEN', nombre='Ventas', tipo='ingreso')
        self.propuesta = {'estado': 'propuesta', 'fecha': '2020-07-25',
                          'descripcion': 'Venta al crédito', 'movimientos': [
            {'cuenta_codigo': 'CLI', 'tipo': 'debe', 'monto': '70000.00'},
            {'cuenta_codigo': 'VEN', 'tipo': 'haber', 'monto': '70000.00'}]}
        self.proveedor = Mock()
        self.proveedor.completar.return_value = json.dumps(self.propuesta)

    def generar(self, hecho):
        return generar_propuesta(hecho, self.proveedor)

    def comprobar_formato(self, texto):
        self.assertEqual(self.generar(texto + ' | Venta al crédito por 70,000 soles')['fecha'], '2020-07-25')

    def test_barras(self):
        self.comprobar_formato('25/07/2020')

    def test_guiones(self):
        self.comprobar_formato('25-07-2020')

    def test_mes_escrito(self):
        self.comprobar_formato('25 de julio de 2020')

    def test_iso(self):
        self.comprobar_formato('2020-07-25')

    def test_fecha_dentro_del_texto(self):
        self.assertEqual(self.generar('El 25/07/2020 se realiza una venta')['fecha'], '2020-07-25')

    def test_sin_fecha_no_acepta_fecha_inventada(self):
        resultado = self.generar('Venta al crédito por 70,000 soles')
        self.assertEqual(resultado['estado'], 'requiere_aclaracion')
        self.assertIn('fecha', resultado['datos_faltantes'])
        self.assertNotIn('movimientos', resultado)

    def test_fecha_invalida(self):
        for fecha in ['31/02/2020', '2020-13-25', '29/02/2019', '25 de inexistente de 2020']:
            with self.subTest(fecha=fecha):
                resultado = self.generar(fecha + ' Venta')
                self.assertEqual(resultado['estado'], 'requiere_aclaracion')
                self.assertIn('no es válida', resultado['pregunta'])
        self.proveedor.completar.assert_not_called()

    def test_fechas_ambiguas(self):
        resultado = self.generar('Venta el 25/07/2020 y pago el 30/07/2020')
        self.assertEqual(resultado['estado'], 'requiere_aclaracion')
        self.proveedor.completar.assert_not_called()

    def test_fechas_con_roles_explicitos(self):
        self.assertEqual(interpretar_fecha('Fecha del hecho: 25/07/2020; vencimiento: 30/07/2020'),
                         ('2020-07-25', None))

    def test_misma_fecha_repetida_no_es_ambigua(self):
        self.assertEqual(interpretar_fecha('25/07/2020 venta, fecha 2020-07-25'), ('2020-07-25', None))

    def test_solo_vencimiento_no_define_fecha_del_hecho(self):
        resultado = self.generar('Venta al crédito con vencimiento: 25/07/2020')
        self.assertEqual(resultado['estado'], 'requiere_aclaracion')

    def test_fecha_del_proveedor_no_sustituye_la_del_hecho(self):
        self.propuesta['fecha'] = '2026-10-02'
        self.proveedor.completar.return_value = json.dumps(self.propuesta)
        self.comprobar_formato('25/07/2020')

    def consultar_api(self):
        with patch('core.services.chatbot.ProveedorGroq', return_value=self.proveedor):
            respuesta = self.client.post(reverse('chatbot_api'), {
                'message': '25/07/2020 | Se realiza una venta por 70,000 soles al crédito'})
        self.assertEqual(respuesta.status_code, 200)
        return respuesta.json()

    def test_caso_completo_y_formulario(self):
        datos = self.consultar_api()
        self.assertEqual(datos['fecha'], '2020-07-25')
        self.assertEqual(datos['movimientos'], self.propuesta['movimientos'])
        self.assertEqual(datos['vista_previa']['fecha'], '2020-07-25')
        pagina = self.client.get(datos['revision_url'])
        self.assertEqual(pagina.context['formulario_inicial']['fecha'], '2020-07-25')
        self.assertContains(pagina, 'value="2020-07-25"')
        self.assertFalse(AsientoContable.objects.exists())
        contexto = self.proveedor.completar.call_args.args[0]
        self.assertIn('70,000 soles al crédito', contexto[1]['content'])
        self.assertIn('CLI', contexto[0]['content'])

    def guardar(self, fecha):
        datos = self.consultar_api()
        return self.client.post(datos['revision_url'], {
            'fecha': fecha, 'descripcion': 'Venta', 'num_movimientos': '2',
            'cuenta_0': self.clientes.pk, 'tipo_0': 'debe', 'monto_0': '70000',
            'cuenta_1': self.ventas.pk, 'tipo_1': 'haber', 'monto_1': '70000'})

    def test_guardado_conserva_fecha(self):
        self.assertEqual(self.guardar('2020-07-25').status_code, 302)
        self.assertEqual(AsientoContable.objects.get().fecha, date(2020, 7, 25))

    def test_fecha_editada_es_la_guardada(self):
        self.assertEqual(self.guardar('2020-08-01').status_code, 302)
        self.assertEqual(AsientoContable.objects.get().fecha, date(2020, 8, 1))

    def test_guardado_rechaza_fecha_invalida(self):
        self.assertContains(self.guardar('2020-02-31'), 'La fecha no es válida')
        self.assertFalse(AsientoContable.objects.exists())

    def test_sesion_revalida_fecha(self):
        for fecha in ['2020-02-31', '20200725', None, '']:
            with self.subTest(fecha=fecha), self.assertRaises(ErrorChatbot):
                validar_propuesta({**self.propuesta, 'fecha': fecha})

    def inventario(self):
        inventario = CuentaContable.objects.create(codigo='INV', nombre='Inventario', tipo='activo')
        for fecha, monto in [('2020-07-01', '15000'), ('2021-01-01', '9000')]:
            asiento = AsientoContable.objects.create(fecha=fecha)
            Movimiento.objects.create(asiento=asiento, cuenta=inventario, tipo='debe', monto=monto)
            Movimiento.objects.create(asiento=asiento, cuenta=self.ventas, tipo='haber', monto=monto)

    def contexto(self):
        contenido = self.proveedor.completar.call_args.args[0][0]['content']
        return json.loads(contenido.split('CONTEXTO DE SALDOS: ', 1)[1])

    def test_inventario_sin_fecha_consulta_saldos_pero_pide_periodo(self):
        self.inventario()
        resultado = self.generar('En el inventario se observa un saldo final de 10,000 soles al cierre del mes')
        contexto = construir_contexto('inventario', list(CuentaContable.objects.all()), None)
        saldo = next(s for s in contexto['saldos'] if s['cuenta_codigo'] == 'INV')
        self.assertEqual(saldo['saldo_debe_menos_haber'], '24000.00')
        self.assertEqual(resultado['estado'], 'requiere_aclaracion')
        self.assertIn('fecha', resultado['datos_faltantes'])

    def test_inventario_con_fecha_usa_saldo_del_periodo(self):
        self.inventario()
        CuentaContable.objects.create(codigo='PER', nombre='Pérdidas de inventario', tipo='gasto')
        propuesta = {'estado': 'propuesta', 'fecha': '2020-07-31',
                     'descripcion': 'Faltante de inventario', 'movimientos': [
                         {'cuenta_codigo': 'PER', 'tipo': 'debe', 'monto': '5000.00'},
                         {'cuenta_codigo': 'INV', 'tipo': 'haber', 'monto': '5000.00'}]}

        def completar(mensajes):
            contexto = json.loads(mensajes[0]['content'].split('CONTEXTO DE SALDOS: ', 1)[1])
            saldo = next(s for s in contexto['saldos'] if s['cuenta_codigo'] == 'INV')
            self.assertEqual(saldo['saldo_debe_menos_haber'], '15000.00')
            return json.dumps(propuesta)

        self.proveedor.completar.side_effect = completar
        resultado = self.generar('31/07/2020 | Inventario final 10,000 soles; registrar el faltante como pérdida')
        self.assertEqual(resultado, propuesta)
        self.assertEqual(AsientoContable.objects.count(), 2)
        saldo = next(s for s in self.contexto()['saldos'] if s['cuenta_codigo'] == 'INV')
        self.assertEqual(saldo['saldo_debe_menos_haber'], '15000.00')
        self.assertEqual(self.contexto()['corte'], '2020-07-31')

    def test_datos_no_disponibles_aclaracion_ampliada(self):
        aclaracion = {'estado': 'requiere_aclaracion', 'pregunta': '¿Cuál es el saldo contable?',
                     'motivo': 'No hay movimientos registrados.',
                     'datos_detectados': {'inventario_final': '10000'},
                     'datos_faltantes': ['saldo_contable']}
        self.proveedor.completar.return_value = json.dumps(aclaracion)
        resultado = self.generar('31/07/2020 | Inventario final 10,000 soles')
        self.assertEqual(resultado['estado'], 'requiere_aclaracion')
        self.assertEqual(resultado['datos_detectados']['inventario_final_informado'], '10000.00')
        self.assertIn('cuenta_inventario', resultado['datos_faltantes'])
        self.proveedor.completar.assert_not_called()

    def test_aclaracion_sin_fecha_preserva_otras_preguntas(self):
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Cuál es el importe?', 'datos_faltantes': ['importe']})
        resultado = self.generar('Venta al crédito')
        self.assertEqual(resultado['datos_faltantes'], ['importe', 'fecha'])
        self.assertIn('importe', resultado['pregunta'])
