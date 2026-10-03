"""Contratos generales del resolver y del flujo HTTP de seguimiento."""
import json
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from core.models import CuentaContable, AsientoContable, Movimiento
from core.plan_cuentas import PLAN_CUENTAS
from core.services.aclaracion_sesion import CLAVE_ACLARACION
from core.services.chatbot import validar_propuesta, ErrorChatbot
from core.services.resolver_aclaraciones import resolver_opciones


class ResolverGeneralTests(TestCase):
    def setUp(self):
        CuentaContable.objects.bulk_create([
            CuentaContable(codigo=c, nombre=n, tipo=t, subcategoria=s)
            for c, n, t, s in PLAN_CUENTAS])
        self.proveedor = Mock()
        parche = patch('core.services.chatbot.ProveedorGroq', return_value=self.proveedor)
        parche.start()
        self.addCleanup(parche.stop)

    def consultar(self, mensaje):
        r = self.client.post(reverse('chatbot_api'), {'message': mensaje})
        self.assertEqual(r.status_code, 200, r.content)
        return r.json()

    def pendiente(self, campo, pregunta, opciones=None, propuesta=None):
        resultado = {'estado': 'requiere_aclaracion', 'pregunta': pregunta,
                     'datos_detectados': {}, 'datos_faltantes': [campo]}
        if opciones is not None:
            resultado['opciones_validas'] = opciones
        if propuesta is not None:
            resultado['opcion_propuesta'] = propuesta
        self.proveedor.completar.return_value = json.dumps(resultado)
        self.consultar('31/07/2020 Venta por S/ 10000')

    def proponer(self):
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'propuesta', 'fecha': '2020-07-31', 'descripcion': 'Venta',
            'movimientos': [{'cuenta_codigo': '12', 'tipo': 'debe', 'monto': '10000'},
                            {'cuenta_codigo': '70', 'tipo': 'haber', 'monto': '10000'}]})

    def test_afirmacion_con_alternativa_unica(self):
        for mensaje in ['sí', 'sí, está bien', 'sí, esa', 'esa opción']:
            with self.subTest(mensaje=mensaje):
                self.pendiente('forma_pago', '¿Fue al crédito?')
                self.proponer()
                self.assertEqual(self.consultar(mensaje)['estado'], 'propuesta')
                self.assertNotIn(CLAVE_ACLARACION, self.client.session)

    def test_afirmacion_sin_referente_no_elige(self):
        self.pendiente('forma_pago', '¿Fue al contado o al crédito?')
        r = self.consultar('sí, está bien')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertNotIn('forma_pago', r['datos_detectados'])

    def test_efectivo_resuelve_forma_pago_sin_perder_opciones(self):
        self.pendiente('forma_pago', '¿Fue al contado o al crédito?')
        self.proponer()
        self.assertEqual(self.consultar('en efectivo')['estado'], 'propuesta')
        contexto = self.proveedor.completar.call_args.args[0][0]['content']
        self.assertIn('"forma_pago": "al contado"', contexto)

    def test_efectivo_con_opciones_explicitas_del_proveedor(self):
        self.pendiente('forma_pago', '¿Cómo se pagó?', [
            {'id': 'contado', 'label': 'Al contado', 'valor': 'al contado'},
            {'id': 'credito', 'label': 'Al crédito', 'valor': 'al crédito'}])
        self.proponer()
        self.assertEqual(self.consultar('efectivo')['estado'], 'propuesta')

    def test_consulta_forma_pago_numera_las_alternativas(self):
        self.pendiente('forma_pago', '¿Fue al contado o al crédito?')
        r = self.consultar('¿Qué opciones hay?')
        self.assertIn('1. Al contado', r['response'])
        self.assertIn('2. Al crédito', r['response'])
        self.proponer()
        self.assertEqual(self.consultar('2')['estado'], 'propuesta')
        contexto = self.proveedor.completar.call_args.args[0][0]['content']
        self.assertIn('"forma_pago": "al crédito"', contexto)

    def test_negacion_retira_referente_de_confirmacion(self):
        self.pendiente('forma_pago', '¿Fue al crédito?')
        self.proveedor.completar.reset_mock()
        self.consultar('no')
        self.assertNotIn('opcion_propuesta', self.client.session[CLAVE_ACLARACION])
        r = self.consultar('sí')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertNotIn('forma_pago', r['datos_detectados'])
        self.proveedor.completar.assert_not_called()

    def test_consulta_general_respeta_opciones_de_cuenta_cerradas(self):
        self.pendiente('cuenta_ingreso', '¿Qué cuenta corresponde?', [
            {'id': 'ventas', 'label': 'Ventas',
             'valor': {'cuenta_codigo': '70', 'cuenta_nombre': 'Ventas'}}])
        self.proveedor.completar.reset_mock()
        r = self.consultar('¿Qué opciones hay?')
        self.assertIn('1.', r['response'])
        opciones = self.client.session[CLAVE_ACLARACION]['opciones']
        self.assertEqual([o['id'] for o in opciones], ['ventas'])
        self.proveedor.completar.assert_not_called()

    def test_consulta_de_opciones_escalares_en_campo_cuenta(self):
        self.pendiente('cuenta_destino', '¿Qué destino corresponde?', [
            {'id': 'local', 'label': 'Local'}, {'id': 'exterior', 'label': 'Exterior'}])
        self.assertEqual(self.consultar('¿Qué opciones hay?')['estado'], 'informativo')
        self.proponer()
        self.assertEqual(self.consultar('2')['estado'], 'propuesta')

    def test_eliminar_cuenta_no_reasigna_numero_visible(self):
        self.pendiente('cuenta_destino', '¿Qué cuenta corresponde?', [
            {'id': 'primera', 'label': 'Primera',
             'valor': {'cuenta_codigo': '62', 'cuenta_nombre': 'Personal'}},
            {'id': 'segunda', 'label': 'Segunda',
             'valor': {'cuenta_codigo': '63', 'cuenta_nombre': 'Terceros'}}])
        CuentaContable.objects.filter(codigo='62').delete()
        self.proveedor.completar.reset_mock()
        r = self.consultar('1')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertNotIn('cuenta_destino', r['datos_detectados'])
        self.assertIn('63', r['pregunta'])
        self.proveedor.completar.assert_not_called()
        self.proponer()
        self.assertEqual(self.consultar('1')['estado'], 'propuesta')

    def test_sin_cuentas_vigentes_no_recurre_al_proveedor(self):
        self.pendiente('cuenta_destino', '¿Qué cuenta corresponde?', [
            {'id': 'destino', 'label': 'Destino',
             'valor': {'cuenta_codigo': '62', 'cuenta_nombre': 'Personal'}}])
        CuentaContable.objects.filter(codigo='62').delete()
        self.proveedor.completar.reset_mock()
        for texto in ['1', 'sí', '62']:
            r = self.consultar(texto)
            self.assertEqual(r['estado'], 'requiere_aclaracion')
            self.assertIn('No quedan cuentas disponibles', r['pregunta'])
            self.assertNotIn('cuenta_destino', r['datos_detectados'])
        self.proveedor.completar.assert_not_called()

    def test_negaciones_conservan_contexto_y_permiten_continuar(self):
        self.pendiente('forma_pago', '¿Fue al contado o al crédito?')
        for mensaje in ['no', 'no es esa', 'ninguna', 'no, fue otra cosa']:
            r = self.consultar(mensaje)
            self.assertEqual(r['estado'], 'requiere_aclaracion')
            self.assertEqual(r['datos_detectados']['fecha'], '2020-07-31')
            self.assertEqual(r['datos_detectados']['importe'], '10000.00')
        self.proponer()
        self.assertEqual(self.consultar('al crédito')['estado'], 'propuesta')

    def test_seleccion_ordinal_de_cuenta(self):
        self.consultar('31/07/2020 Pago de gastos operativos por S/ 100 al contado')
        r = self.consultar('la segunda')
        self.assertEqual(r['estado'], 'propuesta')
        self.assertEqual(r['movimientos'][0]['cuenta_codigo'], '63')

    def test_ambiguedad_reduce_opciones_sin_perder_orden(self):
        CuentaContable.objects.create(codigo='631', nombre='Servicios de terceros locales', tipo='gasto')
        self.consultar('31/07/2020 Pago de gastos operativos por S/ 100 al contado')
        r = self.consultar('terceros')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertIn('631', r['pregunta'])
        self.assertEqual(self.consultar('la segunda')['movimientos'][0]['cuenta_codigo'], '631')

    def test_seleccion_respeta_lista_informativa(self):
        self.consultar('31/07/2020 Pago de gastos operativos por S/ 100 al contado')
        opciones = self.consultar('¿Qué tipos de gasto hay?')['opciones']
        self.assertEqual(self.consultar('la segunda')['movimientos'][0]['cuenta_codigo'],
                         opciones[1]['cuenta_codigo'])

    def test_campos_arbitrarios_y_opcion_propuesta(self):
        opciones = [{'id': 'a', 'etiqueta': 'Incluye impuesto', 'valor': True},
                    {'id': 'b', 'etiqueta': 'No incluye impuesto', 'valor': False}]
        self.pendiente('incluye_impuesto', '¿Confirmas que incluye impuesto?', opciones, 'a')
        self.proponer()
        self.assertEqual(self.consultar('sí')['estado'], 'propuesta')
        contexto = self.proveedor.completar.call_args.args[0][0]['content']
        self.assertIn('"incluye_impuesto": true', contexto)

    def test_equivalencia_semantica_con_conjunto_cerrado(self):
        opciones = [{'id': 'ext', 'etiqueta': 'Servicios profesionales', 'valor': 'Servicios profesionales'}]
        pendiente = {'pregunta_pendiente': '¿Qué servicio fue?', 'campo_pendiente': 'servicio',
                     'datos_detectados': {'importe': '100.00'},
                     'contexto_contable': {'periodo': '2020-07'}}
        proveedor = Mock()
        proveedor.completar.return_value = '{"candidatos":["ext"]}'
        estado, elegidas = resolver_opciones('honorarios del asesor', pendiente, opciones, proveedor)
        self.assertEqual(estado, 'resuelta')
        self.assertEqual(elegidas, opciones)
        enviado = json.loads(proveedor.completar.call_args.args[0][1]['content'])
        self.assertEqual(enviado['contexto_contable']['periodo'], '2020-07')

    def test_semantica_no_admite_ids_inventados_o_multiples(self):
        opciones = [{'id': 'a', 'etiqueta': 'Primera causa', 'valor': 'Primera causa'},
                    {'id': 'b', 'etiqueta': 'Segunda causa', 'valor': 'Segunda causa'}]
        for contenido in ['{"candidatos":["inventado"]}', '{"candidatos":["a","b"]}', 'inválido']:
            proveedor = Mock()
            proveedor.completar.return_value = contenido
            estado, _ = resolver_opciones('ocurrió un incidente', {
                'pregunta_pendiente': '¿Qué causa?', 'datos_detectados': {}}, opciones, proveedor)
            self.assertEqual(estado, 'ambigua')

    def test_opciones_de_cuentas_inventadas_rechazadas(self):
        with self.assertRaises(ErrorChatbot):
            validar_propuesta({'estado': 'requiere_aclaracion', 'pregunta': '¿Esta cuenta?',
                              'opciones_validas': [{'id': 'falsa', 'etiqueta': 'Falsa',
                               'valor': {'cuenta_codigo': '9999', 'cuenta_nombre': 'Falsa'}}]})

    def test_consulta_informativa_de_alternativas_generales(self):
        self.pendiente('operacion', '¿Corresponde a una venta, compra, pago u otro hecho?', [
            {'id': 'v', 'etiqueta': 'Venta', 'valor': 'venta'},
            {'id': 'c', 'etiqueta': 'Compra', 'valor': 'compra'}])
        anterior = dict(self.client.session[CLAVE_ACLARACION])
        r = self.consultar('¿Qué opciones hay?')
        self.assertEqual(r['estado'], 'informativo')
        self.assertIn('1. Venta', r['response'])
        self.assertIn('2. Compra', r['response'])
        self.assertEqual(self.client.session[CLAVE_ACLARACION]['datos_detectados'], anterior['datos_detectados'])

    def test_respuesta_no_sobrescribe_datos_confirmados(self):
        self.pendiente('cuenta_ingreso', '¿Qué cuenta de ingreso: Ventas (70)?')
        sesion = self.client.session
        sesion[CLAVE_ACLARACION]['datos_detectados']['forma_pago'] = 'al contado'
        sesion.save()
        self.proveedor.completar.return_value = '{"candidatos":[]}'
        r = self.consultar('al crédito')
        self.assertEqual(r['datos_detectados']['forma_pago'], 'al contado')

    def test_proveedor_no_repite_preguntas_por_campos_confirmados(self):
        self.pendiente('forma_pago', '¿Fue al contado o al crédito?')
        self.proponer()
        propuesta = self.proveedor.completar.return_value
        self.proveedor.completar.side_effect = [json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Fue al contado o al crédito?',
            'datos_detectados': {}, 'datos_faltantes': ['forma_pago']}), propuesta]
        self.assertEqual(self.consultar('crédito')['estado'], 'propuesta')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)

    def test_inventario_respuestas_cortas_y_semanticas(self):
        asiento = AsientoContable.objects.create(fecha='2020-07-20', descripcion='Compra de mercaderías')
        for codigo, tipo in [('20', 'debe'), ('10', 'haber')]:
            Movimiento.objects.create(asiento=asiento, cuenta=CuentaContable.objects.get(codigo=codigo),
                                      tipo=tipo, monto='50000')
        for respuesta in ['costo de ventas', 'sí, corresponde al costo de las mercaderías vendidas']:
            with self.subTest(respuesta=respuesta):
                self.consultar('Inventario final de 10,000 soles al cierre del mes')
                r = self.consultar('mercaderías')
                self.assertEqual(r['datos_faltantes'], ['causa_ajuste'])
                pendiente = self.client.session[CLAVE_ACLARACION]
                self.assertEqual(pendiente['contexto_contable']['periodo'], '2020-07')
                self.assertTrue(pendiente['contexto_contable']['saldos'])
                self.proveedor.completar.return_value = json.dumps({
                    'estado': 'propuesta', 'fecha': '2020-07-31', 'descripcion': 'Costo de ventas',
                    'movimientos': [{'cuenta_codigo': '69', 'tipo': 'debe', 'monto': '40000'},
                                    {'cuenta_codigo': '20', 'tipo': 'haber', 'monto': '40000'}]})
                self.assertEqual(self.consultar(respuesta)['estado'], 'propuesta')
                self.assertNotIn(CLAVE_ACLARACION, self.client.session)
