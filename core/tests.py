from datetime import date
from decimal import Decimal
from unittest.mock import patch
import json
import os
import requests

from django.db import IntegrityError
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse

from .models import AsientoContable, CuentaContable, Movimiento
from .services.asientos import validar_movimientos


class DiagnosticoGroqTests(SimpleTestCase):
    @override_settings(GROQ_DIAGNOSTICS=True)
    def test_errores_http_se_registran_sin_secretos(self):
        from .services.chatbot import ErrorChatbot, ProveedorGroq

        clave = 'gsk_secreto_prueba'
        for status, codigo in [(400, 'invalid_request_error'), (401, 'invalid_api_key'),
                               (403, 'forbidden'), (404, 'model_not_found'),
                               (429, 'rate_limit_exceeded'), (500, 'server_error')]:
            with self.subTest(status=status):
                respuesta = requests.Response()
                respuesta.status_code = status
                respuesta._content = json.dumps({'error': {
                    'code': codigo, 'type': 'invalid_request_error',
                    'message': f'Fallo {clave} Bearer otro-secreto org_privada\nsegunda linea',
                    'failed_generation': 'datos contables privados',
                }}).encode()
                with patch.dict(os.environ, {'GROQ_API_KEY': clave}), \
                     patch('core.services.chatbot.requests.post', return_value=respuesta), \
                     self.assertLogs('core.services.chatbot', level='ERROR') as logs, \
                     self.assertRaises(ErrorChatbot) as error:
                    ProveedorGroq().completar([{'role': 'user', 'content': 'datos contables privados'}])
                registro = '\n'.join(logs.output)
                self.assertIn(f'HTTP {status}', registro)
                self.assertIn(codigo, registro)
                for secreto in (clave, 'otro-secreto', 'org_privada', 'datos contables privados'):
                    self.assertNotIn(secreto, registro)
                self.assertEqual(str(error.exception), 'No se pudo obtener una respuesta de Groq.')
                self.assertEqual(error.exception.status, 502)

    @override_settings(GROQ_DIAGNOSTICS=True)
    def test_error_html_no_se_imprime(self):
        from .services.chatbot import ErrorChatbot, ProveedorGroq

        respuesta = requests.Response()
        respuesta.status_code = 502
        respuesta._content = b'<html>datos privados del proxy</html>'
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test'}), \
             patch('core.services.chatbot.requests.post', return_value=respuesta), \
             self.assertLogs('core.services.chatbot', level='ERROR') as logs, \
             self.assertRaises(ErrorChatbot):
            ProveedorGroq().completar([])
        self.assertIn('HTTP 502', logs.output[0])
        self.assertNotIn('datos privados', logs.output[0])

    @override_settings(GROQ_DIAGNOSTICS=False)
    def test_detalle_se_puede_desactivar(self):
        from .services.chatbot import ErrorChatbot, ProveedorGroq

        respuesta = requests.Response()
        respuesta.status_code = 404
        respuesta._content = b'{"error":{"message":"detalle del proveedor"}}'
        with patch.dict(os.environ, {'GROQ_API_KEY': 'test'}), \
             patch('core.services.chatbot.requests.post', return_value=respuesta), \
             self.assertLogs('core.services.chatbot', level='ERROR') as logs, \
             self.assertRaises(ErrorChatbot):
            ProveedorGroq().completar([])
        self.assertIn('HTTP 404', logs.output[0])
        self.assertNotIn('detalle del proveedor', logs.output[0])

    def test_timeout_no_expone_excepcion(self):
        from .services.chatbot import ErrorChatbot, ProveedorGroq

        with patch.dict(os.environ, {'GROQ_API_KEY': 'test'}), \
             patch('core.services.chatbot.requests.post', side_effect=requests.Timeout('secreto del proxy')), \
             self.assertLogs('core.services.chatbot', level='ERROR') as logs, \
             self.assertRaises(ErrorChatbot):
            ProveedorGroq().completar([])
        self.assertIn('Timeout', logs.output[0])
        self.assertNotIn('secreto del proxy', logs.output[0])


class ValidacionAsientosTests(TestCase):
    def setUp(self):
        self.caja = CuentaContable.objects.create(codigo='10', nombre='Caja', tipo='activo')
        self.capital = CuentaContable.objects.create(codigo='50', nombre='Capital', tipo='patrimonio')
        self.datos = {
            'fecha': '2026-10-02', 'descripcion': 'Aporte', 'num_movimientos': '2',
            'cuenta_0': str(self.caja.pk), 'tipo_0': 'debe', 'monto_0': '100.00',
            'cuenta_1': str(self.capital.pk), 'tipo_1': 'haber', 'monto_1': '100.00',
        }

    def crear_asiento(self):
        asiento = AsientoContable.objects.create(fecha=date(2026, 10, 1), descripcion='Original')
        Movimiento.objects.create(asiento=asiento, cuenta=self.caja, tipo='debe', monto=50)
        Movimiento.objects.create(asiento=asiento, cuenta=self.capital, tipo='haber', monto=50)
        return asiento

    def test_registro_y_edicion_validos(self):
        self.client.post(reverse('registrar_asiento'), self.datos)
        asiento = AsientoContable.objects.get()
        self.assertEqual(asiento.total_debe, Decimal('100'))
        datos = {**self.datos, 'descripcion': 'Actualizado', 'monto_0': '200', 'monto_1': '200'}
        self.client.post(reverse('editar_asiento', args=[asiento.pk]), datos)
        asiento.refresh_from_db()
        self.assertEqual(asiento.descripcion, 'Actualizado')
        self.assertEqual(asiento.movimientos.count(), 2)
        self.assertEqual(asiento.total_debe, Decimal('200'))
        self.assertTrue(asiento.esta_balanceado)

    def test_ambas_vistas_rechazan_datos_invalidos_sin_cambiar_asiento(self):
        asiento = self.crear_asiento()
        originales = list(asiento.movimientos.values_list('pk', 'cuenta_id', 'tipo', 'monto'))
        casos = [
            {'cuenta_0': '999999'}, {'cuenta_0': 'abc'}, {'monto_0': '0'},
            {'monto_0': '-1'}, {'monto_0': 'NaN'}, {'monto_0': 'Infinity'},
            {'monto_0': 'abc'}, {'monto_0': '100.001'}, {'monto_0': '10000000000'},
            {'num_movimientos': '1'}, {'num_movimientos': 'abc'},
            {'monto_1': '90'}, {'tipo_0': 'otro'}, {'fecha': ''},
        ]
        for cambios in casos:
            for ruta in [reverse('registrar_asiento'), reverse('editar_asiento', args=[asiento.pk])]:
                with self.subTest(cambios=cambios, ruta=ruta):
                    respuesta = self.client.post(ruta, {**self.datos, **cambios})
                    self.assertIn(respuesta.status_code, (200, 302))
                    self.assertEqual(AsientoContable.objects.count(), 1)
                    asiento.refresh_from_db()
                    self.assertEqual(asiento.descripcion, 'Original')
                    self.assertEqual(asiento.fecha, date(2026, 10, 1))
                    self.assertEqual(list(asiento.movimientos.values_list('pk', 'cuenta_id', 'tipo', 'monto')), originales)

    def test_error_de_guardado_revierte_registro_y_edicion(self):
        crear = Movimiento.objects.create

        def fallar_segundo(*args, **kwargs):
            if kwargs['tipo'] == 'haber':
                raise IntegrityError('Fallo simulado')
            return crear(*args, **kwargs)

        with patch('core.views.Movimiento.objects.create', side_effect=fallar_segundo):
            with self.assertRaises(IntegrityError):
                self.client.post(reverse('registrar_asiento'), self.datos)
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(Movimiento.objects.exists())

        asiento = self.crear_asiento()
        originales = list(asiento.movimientos.values_list('pk', 'monto'))
        with patch('core.views.Movimiento.objects.create', side_effect=fallar_segundo):
            with self.assertRaises(IntegrityError):
                self.client.post(reverse('editar_asiento', args=[asiento.pk]), self.datos)
        asiento.refresh_from_db()
        self.assertEqual(asiento.descripcion, 'Original')
        self.assertEqual(asiento.fecha, date(2026, 10, 1))
        self.assertEqual(list(asiento.movimientos.values_list('pk', 'monto')), originales)

    def test_servicio_devuelve_cuentas_y_decimales(self):
        movimientos, errores = validar_movimientos([
            {'cuenta_id': self.caja.pk, 'tipo': 'debe', 'monto': '100.00'},
            {'cuenta_id': self.capital.pk, 'tipo': 'haber', 'monto': '100.00'},
        ])
        self.assertEqual(errores, [])
        self.assertEqual(movimientos[0]['cuenta'], self.caja)
        self.assertEqual(movimientos[0]['monto'], Decimal('100.00'))


class ChatbotTests(TestCase):
    def setUp(self):
        self.caja = CuentaContable.objects.create(codigo='10', nombre='Caja', tipo='activo')
        self.capital = CuentaContable.objects.create(codigo='50', nombre='Capital', tipo='patrimonio')
        # Más de veinte cuentas y ninguna con movimientos: el contexto no debe truncarlas.
        for i in range(21):
            CuentaContable.objects.create(codigo=f'99{i:02}', nombre=f'Cuenta {i}', tipo='gasto')
        self.propuesta = {
            'estado': 'propuesta', 'fecha': '2020-07-25', 'descripcion': 'Aporte de capital en efectivo',
            'movimientos': [
                {'cuenta_codigo': '10', 'tipo': 'debe', 'monto': '100.00'},
                {'cuenta_codigo': '50', 'tipo': 'haber', 'monto': '100.00'},
            ],
        }
        self.entorno = patch.dict(os.environ, {'GROQ_API_KEY': 'clave-de-prueba'})
        self.entorno.start()
        self.addCleanup(self.entorno.stop)
        self.http = patch('core.services.chatbot.requests.post')
        self.proveedor = self.http.start()
        self.addCleanup(self.http.stop)

    def consultar(self, contenido, formato_json=False):
        self.proveedor.return_value.json.return_value = {
            'choices': [{'message': {'content': contenido}}],
        }
        cuentas = list(CuentaContable.objects.values())
        if formato_json:
            respuesta = self.client.post(reverse('chatbot_api'),
                                         {'message': '25/07/2020 | Aporte de capital en efectivo de 100 soles'},
                                         content_type='application/json')
        else:
            respuesta = self.client.post(reverse('chatbot_api'),
                                         {'message': '25/07/2020 | Aporte de capital en efectivo de 100 soles'})
        self.assertEqual(list(CuentaContable.objects.values()), cuentas)
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(Movimiento.objects.exists())
        return respuesta

    def test_propuesta_valida_catalogo_completo_y_compatibilidad(self):
        respuesta = self.consultar(json.dumps(self.propuesta))
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(datos['estado'], 'propuesta')
        self.assertEqual(datos['status'], 'success')
        self.assertEqual(datos['movimientos'], self.propuesta['movimientos'])
        self.assertIn('sin guardar', datos['response'])
        self.assertIn('10 | Debe | S/ 100.00', datos['response'])
        payload = self.proveedor.call_args.kwargs['json']
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        contexto = payload['messages'][0]['content']
        for cuenta in CuentaContable.objects.all():
            self.assertIn(json.dumps(cuenta.codigo), contexto)

    def test_cuenta_inexistente(self):
        self.propuesta['movimientos'][0]['cuenta_codigo'] = '404'
        respuesta = self.consultar(json.dumps(self.propuesta))
        self.assertEqual(respuesta.status_code, 422)
        self.assertIn('no existe', respuesta.json()['error'])
        self.assertNotIn('estado', respuesta.json())

    def test_debe_distinto_de_haber(self):
        self.propuesta['movimientos'][1]['monto'] = '90'
        respuesta = self.consultar(json.dumps(self.propuesta))
        self.assertEqual(respuesta.status_code, 422)
        self.assertIn('no está balanceado', respuesta.json()['error'])

    def test_respuesta_malformada(self):
        casos = ['texto libre', '[]', '{}', 'null',
                 '{"estado":"propuesta","descripcion":"Aporte","movimientos":[null]}',
                 '{"estado":"requiere_aclaracion","pregunta":""}']
        for contenido in casos:
            with self.subTest(contenido=contenido):
                respuesta = self.consultar(contenido)
                self.assertEqual(respuesta.status_code, 502)
                self.assertEqual(respuesta.json()['status'], 'error')
        self.proveedor.return_value.json.return_value = {'choices': []}
        respuesta = self.client.post(reverse('chatbot_api'), {'message': '25/07/2020 | Aporte'})
        self.assertEqual(respuesta.status_code, 502)

    def test_requiere_aclaracion(self):
        respuesta = self.consultar(json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Cuál es el importe del aporte?',
        }))
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['estado'], 'requiere_aclaracion')
        self.assertEqual(respuesta.json()['response'], respuesta.json()['pregunta'])
        self.assertNotIn('movimientos', respuesta.json())

    def test_solicitud_json_y_monto_numerico(self):
        for movimiento in self.propuesta['movimientos']:
            movimiento['monto'] = 100.00
        respuesta = self.consultar(json.dumps(self.propuesta), formato_json=True)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(respuesta.json()['movimientos'][0]['monto'], '100.00')

    def test_reutiliza_validaciones_de_asientos(self):
        casos = [[], [self.propuesta['movimientos'][0]],
                 [{**m, 'monto': '0'} for m in self.propuesta['movimientos']],
                 [{**m, 'monto': '-1'} for m in self.propuesta['movimientos']],
                 [{**m, 'monto': 'NaN'} for m in self.propuesta['movimientos']],
                 [{**m, 'monto': '100.001'} for m in self.propuesta['movimientos']],
                 [{**m, 'tipo': 'otro'} for m in self.propuesta['movimientos']]]
        for movimientos in casos:
            with self.subTest(movimientos=movimientos):
                respuesta = self.consultar(json.dumps({**self.propuesta, 'movimientos': movimientos}))
                self.assertEqual(respuesta.status_code, 422)

    def test_fallo_proveedor(self):
        self.proveedor.side_effect = requests.Timeout('Información interna')
        respuesta = self.consultar(json.dumps(self.propuesta))
        self.assertEqual(respuesta.status_code, 502)
        self.assertNotIn('Información interna', respuesta.json()['error'])

    def test_metodo_y_mensajes_invalidos(self):
        self.assertEqual(self.client.get(reverse('chatbot_api')).status_code, 405)
        self.assertEqual(self.client.post(reverse('chatbot_api'), {'message': ' '}).status_code, 400)
        for cuerpo in ['{', '[]', '{"message":null}']:
            respuesta = self.client.post(reverse('chatbot_api'), cuerpo, content_type='application/json')
            self.assertEqual(respuesta.status_code, 400)
        self.proveedor.assert_not_called()

    def test_proveedor_reemplazable(self):
        from .services.chatbot import generar_propuesta

        class OtroProveedor:
            def completar(proveedor, mensajes):
                return json.dumps(self.propuesta)

        self.assertEqual(generar_propuesta('25/07/2020 | Aporte', proveedor=OtroProveedor())['estado'], 'propuesta')
        self.proveedor.assert_not_called()
        self.assertFalse(AsientoContable.objects.exists())

    def test_falta_clave(self):
        with patch.dict(os.environ, {'GROQ_API_KEY': ''}):
            respuesta = self.client.post(reverse('chatbot_api'), {'message': '25/07/2020 | Aporte'})
        self.assertEqual(respuesta.status_code, 500)
        self.proveedor.assert_not_called()


class RevisionChatbotTests(TestCase):
    setUp = ChatbotTests.setUp
    consultar = ChatbotTests.consultar

    def propuesta_valida(self):
        return self.consultar(json.dumps(self.propuesta)).json()

    def formulario(self, respuesta):
        return self.client.get(respuesta['revision_url'])

    def datos_editados(self):
        return {
            'fecha': '2026-10-03', 'descripcion': 'Aporte corregido manualmente',
            'num_movimientos': '2', 'cuenta_0': str(self.capital.pk), 'tipo_0': 'haber',
            'monto_0': '150.00', 'cuenta_1': str(self.caja.pk), 'tipo_1': 'debe',
            'monto_1': '150.00',
        }

    def test_propuesta_para_vista_previa(self):
        datos = self.propuesta_valida()
        preview = datos['vista_previa']
        self.assertEqual(preview['descripcion'], self.propuesta['descripcion'])
        self.assertEqual(preview['movimientos'][0]['cuenta_codigo'], '10')
        self.assertEqual(preview['movimientos'][0]['cuenta_nombre'], 'Caja')
        self.assertEqual(preview['movimientos'][1]['cuenta_nombre'], 'Capital')
        self.assertEqual(preview['total_debe'], '100.00')
        self.assertEqual(preview['total_haber'], '100.00')
        pagina = self.client.get(reverse('index'))
        self.assertContains(pagina, 'js/chatbot.js')
        self.assertNotContains(pagina, 'async function sendMessage')
        self.assertContains(pagina, 'csrfmiddlewaretoken')

    def test_transferencia_y_precarga_sin_guardar(self):
        datos = self.propuesta_valida()
        self.assertRegex(datos['propuesta_id'], r'^[a-f0-9]{32}$')
        self.assertNotIn('descripcion', datos['revision_url'])
        self.assertIn(datos['propuesta_id'], self.client.session['chatbot_propuestas'])
        respuesta = self.formulario(datos)
        self.assertEqual(respuesta.status_code, 200)
        inicial = respuesta.context['formulario_inicial']
        self.assertEqual(inicial['descripcion'], self.propuesta['descripcion'])
        self.assertEqual(inicial['fecha'], '2020-07-25')
        self.assertEqual(inicial['movimientos'][0]['cuenta_id'], self.caja.pk)
        self.assertEqual(inicial['movimientos'][0]['tipo'], 'debe')
        self.assertEqual(inicial['movimientos'][1]['monto'], '100.00')
        self.assertContains(respuesta, 'id="asiento-inicial"')
        self.assertContains(respuesta, 'value="Aporte de capital en efectivo"')
        self.assertContains(respuesta, 'INICIAL.movimientos.forEach')
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(Movimiento.objects.exists())

    def test_modificacion_manual_y_guardado_normal(self):
        datos = self.propuesta_valida()
        self.formulario(datos)
        respuesta = self.client.post(datos['revision_url'], self.datos_editados())
        self.assertRedirects(respuesta, reverse('libro_diario'))
        asiento = AsientoContable.objects.get()
        self.assertEqual(asiento.fecha, date(2026, 10, 3))
        self.assertEqual(asiento.descripcion, 'Aporte corregido manualmente')
        self.assertEqual(asiento.total_debe, Decimal('150'))
        self.assertTrue(asiento.esta_balanceado)
        movimientos = list(asiento.movimientos.order_by('pk'))
        self.assertEqual(movimientos[0].cuenta, self.capital)
        self.assertEqual(movimientos[0].tipo, 'haber')
        self.assertNotIn(datos['propuesta_id'], self.client.session['chatbot_propuestas'])

    def test_validacion_final_no_confia_en_navegador(self):
        datos = self.propuesta_valida()
        casos = [
            {'cuenta_0': '404'}, {'monto_0': '0'}, {'monto_0': '-1'},
            {'num_movimientos': '1'}, {'monto_0': '90'}, {'tipo_0': 'otro'},
            {'fecha': '2026-02-30'}, {'num_movimientos': '1000000000'},
        ]
        for cambios in casos:
            with self.subTest(cambios=cambios):
                respuesta = self.client.post(datos['revision_url'], {**self.datos_editados(), **cambios})
                self.assertEqual(respuesta.status_code, 200)
                self.assertFalse(AsientoContable.objects.exists())
                self.assertFalse(Movimiento.objects.exists())
                self.assertIn(datos['propuesta_id'], self.client.session['chatbot_propuestas'])

    def test_error_conserva_datos_editados(self):
        datos = self.propuesta_valida()
        editados = {**self.datos_editados(), 'monto_1': '80.00'}
        respuesta = self.client.post(datos['revision_url'], editados)
        inicial = respuesta.context['formulario_inicial']
        self.assertEqual(inicial['descripcion'], editados['descripcion'])
        self.assertEqual(inicial['fecha'], editados['fecha'])
        self.assertEqual(inicial['movimientos'][1]['monto'], '80.00')
        self.assertContains(respuesta, 'no está balanceado')

    def test_propuesta_invalida_no_llega_al_formulario(self):
        self.propuesta['movimientos'][0]['cuenta_codigo'] = '404'
        respuesta = self.consultar(json.dumps(self.propuesta))
        self.assertEqual(respuesta.status_code, 422)
        self.assertNotIn('revision_url', respuesta.json())
        self.assertFalse(self.client.session.get('chatbot_propuestas'))

    def test_revalida_cuentas_al_abrir_formulario(self):
        datos = self.propuesta_valida()
        self.caja.delete()
        respuesta = self.formulario(datos)
        self.assertRedirects(respuesta, reverse('registrar_asiento'))
        self.assertNotIn(datos['propuesta_id'], self.client.session['chatbot_propuestas'])
        self.assertFalse(AsientoContable.objects.exists())

    def test_rechaza_propuesta_de_sesion_descuadrada(self):
        datos = self.propuesta_valida()
        sesion = self.client.session
        sesion['chatbot_propuestas'][datos['propuesta_id']]['resultado']['movimientos'][0]['monto'] = '90'
        sesion.save()
        respuesta = self.formulario(datos)
        self.assertRedirects(respuesta, reverse('registrar_asiento'))
        self.assertNotIn(datos['propuesta_id'], self.client.session['chatbot_propuestas'])

    def test_sesion_sin_propuesta_y_aislamiento(self):
        respuesta = self.client.get(reverse('registrar_asiento'))
        self.assertEqual(respuesta.context['formulario_inicial']['movimientos'], [])
        self.assertEqual(respuesta.context['formulario_inicial']['descripcion'], '')
        self.assertRedirects(self.client.get(reverse('registrar_asiento') + '?propuesta=inventada'),
                             reverse('registrar_asiento'))
        datos = self.propuesta_valida()
        self.assertRedirects(Client().get(datos['revision_url']), reverse('registrar_asiento'))

    def test_propuesta_caducada_y_limite_sesion(self):
        for _ in range(6):
            datos = self.propuesta_valida()
        self.assertEqual(len(self.client.session['chatbot_propuestas']), 5)
        sesion = self.client.session
        sesion['chatbot_propuestas'][datos['propuesta_id']]['creada_en'] -= 1801
        sesion.save()
        self.assertRedirects(self.formulario(datos), reverse('registrar_asiento'))

    def test_aclaracion_y_errores_no_crean_propuestas(self):
        casos = [
            ({'estado': 'requiere_aclaracion', 'pregunta': '¿Cuál es el importe?'}, 200),
            ({**self.propuesta, 'movimientos': []}, 422),
            ({'estado': 'desconocido'}, 502),
        ]
        for resultado, status in casos:
            with self.subTest(status=status):
                respuesta = self.consultar(json.dumps(resultado))
                self.assertEqual(respuesta.status_code, status)
                self.assertNotIn('revision_url', respuesta.json())
                self.assertFalse(self.client.session.get('chatbot_propuestas'))

    def test_csrf_en_chat_y_guardado(self):
        cliente = Client(enforce_csrf_checks=True)
        pagina = cliente.get(reverse('index'))
        self.assertContains(pagina, 'csrfmiddlewaretoken')
        self.assertEqual(cliente.post(reverse('chatbot_api'), {'message': '25/07/2020 | Aporte'}).status_code, 403)
        self.proveedor.assert_not_called()
        self.proveedor.return_value.json.return_value = {
            'choices': [{'message': {'content': json.dumps(self.propuesta)}}],
        }
        respuesta = cliente.post(reverse('chatbot_api'), {'message': '25/07/2020 | Aporte'},
                                 HTTP_X_CSRFTOKEN=cliente.cookies['csrftoken'].value)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(cliente.post(respuesta.json()['revision_url'], self.datos_editados()).status_code, 403)
        self.assertFalse(AsientoContable.objects.exists())

    def test_textos_no_se_interpretan_como_html(self):
        self.propuesta['descripcion'] = '</script><img src=x onerror=alert(1)>'
        self.caja.nombre = '</option><script>alert(1)</script>'
        self.caja.save()
        datos = self.propuesta_valida()
        respuesta = self.formulario(datos)
        self.assertContains(respuesta, '\\u003C/script\\u003E')
        self.assertNotContains(respuesta, '<img src=x onerror=alert(1)>')
        self.assertNotContains(respuesta, '</option><script>alert(1)</script>')
