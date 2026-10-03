"""Regresiones del resolver puro y la máquina de estados HTTP/sesión."""
import json
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from core.models import AsientoContable, CuentaContable, Movimiento
from core.plan_cuentas import PLAN_CUENTAS
from core.services.aclaracion_sesion import CLAVE_ACLARACION
from core.services.chatbot import ErrorChatbot
from core.services.resolver_aclaraciones import resolver_opcion_aclaracion


OPCIONES = [
    {'id': 'costo_ventas', 'label': 'Costo de las mercaderías vendidas',
     'sinonimos': ['costo de ventas', 'mercaderías vendidas', 'vendidas']},
    {'id': 'perdida', 'label': 'Pérdida'},
    {'id': 'otra', 'label': 'Otra causa'},
]


class ResolverDeterministaTests(SimpleTestCase):
    def elegir(self, texto, esperado='costo_ventas', opciones=None):
        estado, opciones = resolver_opcion_aclaracion(texto, opciones or OPCIONES)
        self.assertEqual(estado, 'resuelta')
        self.assertEqual([o['id'] for o in opciones], [esperado])

    def test_vendidas(self):
        self.elegir('vendidas')

    def test_mercaderias_vendidas(self):
        self.elegir('mercaderías vendidas')

    def test_costo_de_ventas(self):
        self.elegir('costo de ventas')

    def test_numero_visible(self):
        self.elegir('1')

    def test_ordinal(self):
        self.elegir('la primera')

    def test_label_y_normalizacion(self):
        for texto in ['Costo de las mercaderías vendidas', '  ¡MERCADERÍAS,  VENDIDAS! ',
                      '  OPCIÓN 1. ', 'si, corresponde al costo de las mercaderías vendidas']:
            with self.subTest(texto=texto):
                self.elegir(texto)
        self.elegir('¡PÉRDIDA!', 'perdida')

    def test_sinonimos_son_generales(self):
        self.elegir('¡HONORARIOS!', 'servicio', [
            {'id': 'servicio', 'label': 'Asesoría profesional', 'sinonimos': ['honorarios']},
            {'id': 'otro', 'label': 'Alquiler'}])

    def test_coincidencia_multiple(self):
        opciones = [{'id': 'a', 'label': 'Servicios locales'},
                    {'id': 'b', 'label': 'Servicios externos'}]
        estado, candidatas = resolver_opcion_aclaracion('servicios', opciones)
        self.assertEqual(estado, 'ambigua')
        self.assertEqual(candidatas, opciones)

    def test_sinonimos_duplicados(self):
        opciones = [{'id': i, 'label': i, 'sinonimos': ['común']} for i in ['a', 'b']]
        self.assertEqual(resolver_opcion_aclaracion('comun', opciones)[0], 'ambigua')

    def test_respuestas_invalidas_y_ambiguas(self):
        for texto in ['cualquier cosa', '', '...', '0', '999', 'sí', 'esa opción',
                      'vendidas o pérdida', 'no sé', 'no vendidas']:
            with self.subTest(texto=texto):
                self.assertNotEqual(resolver_opcion_aclaracion(texto, OPCIONES)[0], 'resuelta')

    def test_afirmacion_exige_referente_explicito(self):
        for texto in ['sí', 'sí, esa', 'esa opción']:
            with self.subTest(texto=texto):
                self.assertEqual(resolver_opcion_aclaracion(texto, OPCIONES, 'costo_ventas'),
                                 ('resuelta', [OPCIONES[0]]))
                self.assertNotEqual(resolver_opcion_aclaracion(texto, OPCIONES[:1])[0], 'resuelta')

    def test_codigos_de_cuentas(self):
        opciones = [{'id': 'externo', 'label': 'Servicios de terceros',
                     'valor': {'cuenta_codigo': 'EXT.01', 'cuenta_nombre': 'Servicios de terceros'}}]
        for texto in ['EXT.01', 'cuenta ext.01', 'terceros', '1']:
            self.elegir(texto, 'externo', opciones)

    def test_codigo_y_numero_en_conflicto_no_desempatan(self):
        opciones = [{'id': 'a', 'label': 'Caja', 'valor': {'cuenta_codigo': '2'}},
                    {'id': 'b', 'label': 'Banco', 'valor': {'cuenta_codigo': '1'}}]
        self.assertEqual(resolver_opcion_aclaracion('1', opciones)[0], 'ambigua')
        self.elegir('cuenta 1', 'b', opciones)
        self.elegir('opción 1', 'a', opciones)

    def test_ordinal_no_oculta_duda_o_alternativas(self):
        for texto in ['la primera o pérdida', 'tal vez la primera',
                      'quizá la primera', 'la primera o cualquier otra']:
            with self.subTest(texto=texto):
                self.assertNotEqual(resolver_opcion_aclaracion(texto, OPCIONES)[0], 'resuelta')

    def test_ordinal_solo_se_admite_como_seleccion_completa(self):
        for texto in ['la primera no sé si corresponde', 'la primera fue descartada']:
            with self.subTest(texto=texto):
                self.assertNotEqual(resolver_opcion_aclaracion(texto, OPCIONES)[0], 'resuelta')


class FlujoDeterministaTests(TestCase):
    def setUp(self):
        CuentaContable.objects.bulk_create([
            CuentaContable(codigo=c, nombre=n, tipo=t, subcategoria=s) for c, n, t, s in PLAN_CUENTAS])
        asiento = AsientoContable.objects.create(fecha='2020-07-20', descripcion='Compra de mercaderías')
        for codigo, tipo in [('20', 'debe'), ('10', 'haber')]:
            Movimiento.objects.create(asiento=asiento, cuenta=CuentaContable.objects.get(codigo=codigo),
                                      tipo=tipo, monto='50000')
        self.proveedor = Mock()
        # Cualquier llamada accidental hace fallar la petición, incluso después de resolver.
        self.proveedor.completar.side_effect = AssertionError('No debe llamar a Groq')
        parche = patch('core.services.chatbot.ProveedorGroq', return_value=self.proveedor)
        parche.start()
        self.addCleanup(parche.stop)

    def consultar(self, texto):
        respuesta = self.client.post(reverse('chatbot_api'), {'message': texto})
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    def iniciar(self):
        self.consultar('Inventario final de 10,000 soles al cierre del mes')
        return self.consultar('mercaderías')

    def test_sesion_estructurada_y_presentacion(self):
        r = self.iniciar()
        pendiente = self.client.session[CLAVE_ACLARACION]
        self.assertEqual(pendiente['campo_pendiente'], 'causa_ajuste')
        self.assertEqual(pendiente['pregunta'], r['pregunta'])
        self.assertEqual(pendiente['opciones'][0]['id'], 'costo_ventas')
        self.assertIn('vendidas', pendiente['opciones'][0]['sinonimos'])
        for texto in ['1. Costo de las mercaderías vendidas', '2. Pérdida', '3. Otra causa']:
            self.assertIn(texto, r['response'])
        self.assertNotRegex(r['response'], r'\([012]\)|\(costo_ventas\)')

    def test_todas_las_variantes_generan_propuesta_sin_groq(self):
        for texto in ['vendidas', 'mercaderías vendidas', 'costo de ventas', '1', 'la primera']:
            with self.subTest(texto=texto):
                self.iniciar()
                r = self.consultar(texto)
                self.assertEqual(r['estado'], 'propuesta')
                self.assertEqual(r['fecha'], '2020-07-31')
                self.assertEqual(r['movimientos'], [
                    {'cuenta_codigo': '69', 'tipo': 'debe', 'monto': '40000.00'},
                    {'cuenta_codigo': '20', 'tipo': 'haber', 'monto': '40000.00'}])
                self.assertIn('revision_url', r)
                self.assertNotIn(CLAVE_ACLARACION, self.client.session)
        self.proveedor.completar.assert_not_called()
        self.assertEqual(AsientoContable.objects.count(), 1)

    def test_invalida_y_ambigua_conservan_contexto_sin_groq(self):
        self.iniciar()
        anterior = self.client.session[CLAVE_ACLARACION]
        for texto in ['no sé', 'vendidas o pérdida', 'xyz', 'sí', '0', '999']:
            r = self.consultar(texto)
            self.assertEqual(r['estado'], 'requiere_aclaracion')
            self.assertEqual(r['datos_detectados'], anterior['datos_detectados'])
            self.assertNotRegex(r['response'], r'\([012]\)|\(costo_ventas\)')
            posterior = self.client.session[CLAVE_ACLARACION]
            for campo in ['mensaje_original', 'contexto', 'contexto_contable']:
                self.assertEqual(posterior[campo], anterior[campo])
        self.assertEqual(self.consultar('vendidas')['estado'], 'propuesta')
        self.proveedor.completar.assert_not_called()

    def test_cuenta_ambigua_pide_seleccion_y_conserva_causa(self):
        CuentaContable.objects.create(codigo='COS', nombre='Costo de ventas', tipo='gasto')
        self.iniciar()
        r = self.consultar('vendidas')
        self.assertEqual(r['datos_faltantes'], ['cuenta_ajuste'])
        self.assertEqual(r['datos_detectados']['causa_ajuste'], 'costo_ventas')
        self.assertEqual(r['datos_detectados']['diferencia'], '40000.00')
        self.assertEqual(self.consultar('COS')['movimientos'][0]['cuenta_codigo'], 'COS')
        self.proveedor.completar.assert_not_called()

    def test_catalogo_personalizado_sin_codigo_fijo(self):
        CuentaContable.objects.filter(codigo='69').update(codigo='COS')
        self.iniciar()
        self.assertEqual(self.consultar('vendidas')['movimientos'][0]['cuenta_codigo'], 'COS')

    def test_recalcula_saldo_al_continuar(self):
        self.iniciar()
        Movimiento.objects.filter(cuenta__codigo='20').update(monto='55000')
        self.assertEqual(self.consultar('vendidas')['movimientos'][0]['monto'], '45000.00')

    def test_perdida_no_inventa_contrapartida(self):
        self.iniciar()
        r = self.consultar('pérdida')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertEqual(r['datos_detectados']['causa_ajuste'], 'perdida')
        self.assertEqual(r['datos_faltantes'], ['cuenta_ajuste'])

    def test_opciones_legacy_siguen_funcionando(self):
        self.iniciar()
        sesion = self.client.session
        pendiente = sesion[CLAVE_ACLARACION]
        pendiente.pop('opciones')
        pendiente['campo_pendiente'] = 'causa_y_tratamiento_de_la_diferencia'
        pendiente['datos_faltantes'] = [pendiente['campo_pendiente']]
        pendiente['opciones_validas'] = [
            {'id': str(i), 'etiqueta': o['label'], 'valor': o['label']} for i, o in enumerate(OPCIONES)]
        sesion.save()
        r = self.consultar('xyz')
        self.assertNotRegex(r['response'], r'\([012]\)')
        self.assertEqual(self.consultar('vendidas')['estado'], 'propuesta')

    def test_forma_pago_ambigua_no_se_completa_por_detector(self):
        self.proveedor.completar.side_effect = None
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Fue al contado o al crédito?',
            'datos_faltantes': ['forma_pago']})
        self.consultar('31/07/2020 Venta por S/ 100')
        self.proveedor.completar.reset_mock()
        self.proveedor.completar.side_effect = AssertionError('La respuesta es ambigua')
        r = self.consultar('al contado o al crédito')
        self.assertNotIn('forma_pago', r['datos_detectados'])
        self.proveedor.completar.assert_not_called()

    def test_confirmacion_propuesta_explicita(self):
        for texto in ['sí', 'sí, esa', 'esa opción']:
            self.iniciar()
            sesion = self.client.session
            sesion[CLAVE_ACLARACION]['opcion_propuesta'] = 'costo_ventas'
            sesion[CLAVE_ACLARACION]['pregunta'] = '¿Confirmas costo de las mercaderías vendidas?'
            sesion.save()
            self.assertEqual(self.consultar(texto)['estado'], 'propuesta')

    def test_repeticion_del_modelo_no_es_502(self):
        self.proveedor.completar.side_effect = None
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Fue al contado o al crédito?',
            'datos_faltantes': ['forma_pago']})
        self.consultar('31/07/2020 Venta por S/ 100')
        r = self.consultar('crédito')
        self.assertEqual(r['estado'], 'requiere_aclaracion')
        self.assertEqual(r['datos_detectados']['forma_pago'], 'al crédito')
        self.assertNotIn('forma_pago', r['datos_faltantes'])

    def test_fallo_real_del_proveedor_sigue_siendo_502(self):
        self.proveedor.completar.side_effect = ErrorChatbot('No se pudo obtener una respuesta de Groq.')
        r = self.client.post(reverse('chatbot_api'), {'message': '31/07/2020 Venta por S/ 100'})
        self.assertEqual(r.status_code, 502)
