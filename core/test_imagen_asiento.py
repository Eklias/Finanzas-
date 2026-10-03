import io
import json
from unittest.mock import Mock, patch

from PIL import Image
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase
from django.urls import resolve, reverse

from . import views
from .models import AsientoContable, CuentaContable, Movimiento


class ImagenAsientoTests(TestCase):
    def setUp(self):
        CuentaContable.objects.create(codigo='10', nombre='Caja', tipo='activo')
        self.url = reverse('procesar_imagen_asiento')

    def imagen(self, name='comprobante.png'):
        output = io.BytesIO()
        with Image.new('RGB', (10, 10), 'white') as image:
            image.save(output, format='PNG')
        return SimpleUploadedFile(name, output.getvalue(), content_type='image/png')

    def test_ruta_y_plantilla_conectadas(self):
        self.assertEqual(resolve(self.url).func, views.procesar_imagen_asiento)
        response = self.client.get(reverse('registrar_asiento'))
        self.assertContains(response, 'type="file" name="imagenes"')
        self.assertContains(response, f'data-url="{self.url}"')
        self.assertContains(response, 'js/asiento_ocr.js')
        self.assertContains(response, 'id="ocrTextoDetectado"')
        self.assertNotContains(response, '<<<<<<<')
        self.assertEqual(response.context['cuentas_json'][0]['codigo'], '10')
        self.assertEqual(response.context['cuentas_json'][0]['id'], CuentaContable.objects.get(codigo='10').pk)
        self.assertEqual(response.context['cuentas_json'][0]['nombre'], 'Caja')
        self.assertEqual(response.context['formulario_inicial']['movimientos'], [])

    def test_metodo_y_archivo_requeridos(self):
        self.assertEqual(self.client.get(self.url).status_code, 405)
        self.assertEqual(self.client.post(self.url).status_code, 400)
        invalid = SimpleUploadedFile('falso.png', b'no es imagen', content_type='image/png')
        self.assertEqual(self.client.post(self.url, {'imagenes': invalid}).status_code, 400)

    @patch('core.views.load_dotenv')
    @patch.dict('os.environ', {'GROQ_API_KEY': 'test'})
    @patch('core.views.requests.post')
    @patch('core.views.pytesseract.image_to_string', side_effect=['Aporte de capital', 'Venta'])
    def test_multipart_multiple_devuelve_texto_y_operaciones_sin_guardar(self, ocr, provider, dotenv):
        operation = {'fecha': '2026-10-03', 'glosa': 'Aporte', 'movimientos': []}
        provider.return_value = Mock(status_code=200)
        provider.return_value.json.return_value = {
            'choices': [{'message': {'content': json.dumps({'operaciones': [operation]})}}],
        }
        response = self.client.post(self.url, {'imagenes': [self.imagen(), self.imagen('otra.png')]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(ocr.call_count, 2)
        self.assertIn('Aporte de capital', response.json()['texto_ocr_detectado'])
        self.assertIn('Venta', response.json()['texto_ocr_detectado'])
        self.assertEqual(response.json()['operaciones'], [operation])
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(Movimiento.objects.exists())

    @patch('core.views.load_dotenv')
    @patch.dict('os.environ', {'GROQ_API_KEY': ''})
    @patch('core.views.pytesseract.image_to_string', return_value='Texto legible')
    def test_fallo_ia_conserva_texto_ocr(self, ocr, dotenv):
        response = self.client.post(self.url, {'imagen': self.imagen()})
        self.assertEqual(response.status_code, 500)
        self.assertIn('Texto legible', response.json()['texto_ocr_detectado'])

    def test_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.get(reverse('registrar_asiento'))
        self.assertEqual(client.post(self.url, {'texto': 'Aporte'}).status_code, 403)
        response = client.post(self.url, {}, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(response.status_code, 400)

    @patch('core.views.load_dotenv')
    @patch.dict('os.environ', {'GROQ_API_KEY': 'test'})
    @patch('core.views.requests.post')
    def test_catalogo_real_en_prompt_y_caso_aporte_sin_guardar(self, provider, dotenv):
        CuentaContable.objects.create(codigo='CAP-01', nombre='Capital registrado',
                                     tipo='patrimonio', subcategoria='patrimonio')
        operation = {'fecha': '2020-07-08', 'glosa': 'Creación de empresa', 'movimientos': [
            {'codigo_cuenta': 10, 'nombre_cuenta': 'Nombre inventado', 'tipo': 'debe', 'monto': 100000},
            {'codigo_cuenta': ' CAP-01 ', 'tipo': 'haber', 'monto': 100000},
        ]}
        provider.return_value = Mock(status_code=200)
        provider.return_value.json.return_value = {
            'choices': [{'message': {'content': json.dumps({'operaciones': [operation]})}}]}
        session = self.client.session
        session['chatbot_propuestas'] = {'prueba': {'creada_en': 1, 'resultado': {}}}
        session.save()
        response = self.client.post(self.url, {'texto': '08/07/2020 Se crea una empresa con 100,000 al contado'})
        self.assertEqual(response.status_code, 200)
        payload = provider.call_args.kwargs['json']
        prompt = payload['messages'][0]['content']
        catalogo = json.loads(prompt.split('Catálogo real de cuentas (JSON):\n')[1])
        self.assertEqual(catalogo, list(CuentaContable.objects.values('codigo', 'nombre', 'tipo', 'subcategoria')))
        self.assertIn('ÚNICAMENTE códigos existentes', prompt)
        self.assertIn('No inventes códigos', prompt)
        self.assertIn('pendiente_revision: true', prompt)
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        result = response.json()['operaciones'][0]
        self.assertEqual(result['fecha'], '2020-07-08')
        self.assertEqual(result['glosa'], 'Creación de empresa')
        self.assertEqual([m['codigo_cuenta'] for m in result['movimientos']], ['10', 'CAP-01'])
        self.assertEqual([m['nombre_cuenta'] for m in result['movimientos']], ['Caja', 'Capital registrado'])
        self.assertTrue(all(m['monto'] == 100000 and not m['pendiente_revision'] for m in result['movimientos']))
        self.assertEqual(self.client.session['chatbot_propuestas'], session['chatbot_propuestas'])
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(Movimiento.objects.exists())

    @patch('core.views.load_dotenv')
    @patch.dict('os.environ', {'GROQ_API_KEY': 'test'})
    @patch('core.views.requests.post')
    def test_codigos_fuera_del_catalogo_o_inciertos_quedan_pendientes(self, provider, dotenv):
        CuentaContable.objects.create(codigo='101', nombre='Caja general', tipo='activo')
        CuentaContable.objects.create(codigo='102', nombre='Caja chica', tipo='activo')
        for codigo, pendiente in [('999', False), ('1', False), (None, True),
                                  ('', False), ('10', True), ('010', False)]:
            with self.subTest(codigo=codigo, pendiente=pendiente):
                provider.return_value = Mock(status_code=200)
                provider.return_value.json.return_value = {'choices': [{'message': {'content': json.dumps({
                    'operaciones': [{'movimientos': [{'codigo_cuenta': codigo, 'nombre_cuenta': 'Caja',
                        'pendiente_revision': pendiente, 'tipo': 'debe', 'monto': 20}]}]})}}]}
                response = self.client.post(self.url, {'texto': 'Operación'})
                self.assertEqual(response.status_code, 200)
                movimiento = response.json()['operaciones'][0]['movimientos'][0]
                self.assertIsNone(movimiento['codigo_cuenta'])
                self.assertEqual(movimiento['nombre_cuenta'], '')
                self.assertTrue(movimiento['pendiente_revision'])
                self.assertIn('manualmente', movimiento['motivo_revision'])

    def test_catalogo_vacio_o_ambiguo_no_resuelve(self):
        for catalogo in [[], [{'codigo': '10', 'nombre': 'Caja'}, {'codigo': ' 10 ', 'nombre': 'Otra'}]]:
            with self.subTest(catalogo=catalogo):
                operaciones = [{'movimientos': [{'codigo_cuenta': '10', 'tipo': 'debe', 'monto': 20}]}]
                views._validar_cuentas_ocr(operaciones, catalogo)
                self.assertIsNone(operaciones[0]['movimientos'][0]['codigo_cuenta'])
                self.assertTrue(operaciones[0]['movimientos'][0]['pendiente_revision'])

    @patch('core.views.load_dotenv')
    @patch.dict('os.environ', {'GROQ_API_KEY': 'test'})
    @patch('core.views.requests.post')
    def test_movimientos_malformados_no_se_precargan_y_conservan_ocr(self, provider, dotenv):
        for operacion in [None, {'movimientos': None}, {'movimientos': [None]},
                          {'movimientos': [{'tipo': 'activo', 'monto': 20}]},
                          {'movimientos': [{'tipo': 'debe'}]},
                          {'movimientos': [{'tipo': 'debe', 'monto': 'NaN'}]}]:
            with self.subTest(operacion=operacion):
                provider.return_value = Mock(status_code=200)
                provider.return_value.json.return_value = {'choices': [{'message': {'content': json.dumps({
                    'operaciones': [operacion]})}}]}
                response = self.client.post(self.url, {'texto': 'Texto legible'})
                self.assertEqual(response.status_code, 502)
                self.assertEqual(response.json()['texto_ocr_detectado'], 'Texto legible')
