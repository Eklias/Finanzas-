import json
from unittest.mock import Mock, patch

import requests
from django.test import TestCase
from django.urls import reverse

from core.models import AsientoContable, CuentaContable, Movimiento
from core.plan_cuentas import PLAN_CUENTAS
from core.services.chatbot import generar_propuesta


class AclaracionesContablesTests(TestCase):
    def setUp(self):
        CuentaContable.objects.bulk_create([
            CuentaContable(codigo=c, nombre=n, tipo=t, subcategoria=s)
            for c, n, t, s in PLAN_CUENTAS
        ])
        self.proveedor = Mock()

    def consultar(self, hecho):
        with patch('core.services.chatbot.ProveedorGroq', return_value=self.proveedor):
            return self.client.post(reverse('chatbot_api'), {'message': hecho})

    def test_gastos_operativos_ambiguos_conservan_datos_y_no_consultan_groq(self):
        for importe in ['20,000 soles', 'S/ 20,000']:
            with self.subTest(importe=importe):
                respuesta = self.consultar(f'31/07/2020 Se pagan gastos operativos por {importe} al contado')
                self.assertEqual(respuesta.status_code, 200)
                datos = respuesta.json()
                self.assertEqual(datos['estado'], 'requiere_aclaracion')
                self.assertTrue(datos['motivo'])
                self.assertEqual(datos['datos_faltantes'], ['tipo_gasto_operativo'])
                self.assertEqual(datos['datos_detectados'], {
                    'fecha': '2020-07-31', 'importe': '20000.00', 'moneda': 'PEN',
                    'forma_pago': 'al contado', 'contrapartida': {
                        'cuenta_codigo': '10', 'cuenta_nombre': 'Efectivo y Equivalentes de Efectivo',
                        'tipo': 'haber', 'monto': '20000.00'},
                })
                for cuenta in CuentaContable.objects.filter(codigo__in=['62', '63', '64', '65']):
                    self.assertIn(f'{cuenta.nombre} ({cuenta.codigo})', datos['pregunta'])
                self.assertEqual(datos['response'], datos['pregunta'])
                self.assertNotIn('movimientos', datos)
                self.assertNotIn('revision_url', datos)
        self.proveedor.completar.assert_not_called()
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(Movimiento.objects.exists())

    def comprobar_especifico(self, concepto, codigo):
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'propuesta', 'fecha': '2026-10-02', 'descripcion': concepto,
            'movimientos': [
                {'cuenta_codigo': codigo, 'tipo': 'debe', 'monto': '20000.00'},
                {'cuenta_codigo': '10', 'tipo': 'haber', 'monto': '20000.00'},
            ],
        })
        respuesta = self.consultar(f'31/07/2020 Se pagan {concepto} por S/ 20,000 al contado')
        self.assertEqual(respuesta.status_code, 200)
        datos = respuesta.json()
        self.assertEqual(datos['estado'], 'propuesta')
        self.assertEqual(datos['fecha'], '2020-07-31')
        self.assertEqual(datos['movimientos'][0]['cuenta_codigo'], codigo)
        self.assertEqual(datos['vista_previa']['total_debe'], '20000.00')
        self.proveedor.completar.assert_called_once()
        self.assertFalse(AsientoContable.objects.exists())

    def test_gastos_de_personal_especificos(self):
        self.comprobar_especifico('gastos de personal', '62')

    def test_servicios_de_terceros_especificos(self):
        self.comprobar_especifico('servicios de terceros', '63')

    def test_tributos_especificos(self):
        self.comprobar_especifico('tributos', '64')

    def test_otros_gastos_de_gestion_especificos(self):
        self.comprobar_especifico('otros gastos de gestión', '65')

    def test_opciones_y_contrapartida_usan_catalogo_real_personalizado(self):
        CuentaContable.objects.all().delete()
        CuentaContable.objects.create(codigo='CAJ', nombre='Caja', tipo='activo')
        CuentaContable.objects.create(codigo='PER', nombre='Gastos de personal de planta', tipo='gasto')
        CuentaContable.objects.create(codigo='GAS', nombre='Gastos operativos', tipo='gasto')
        datos = self.consultar('31/07/2020 Pago de gastos operativos por S/ 20,000 al contado').json()
        self.assertIn('Gastos de personal de planta (PER)', datos['pregunta'])
        self.assertNotIn('(63)', datos['pregunta'])
        self.assertNotIn('(GAS)', datos['pregunta'])
        self.assertEqual(datos['datos_detectados']['contrapartida']['cuenta_codigo'], 'CAJ')
        self.proveedor.completar.assert_not_called()

    def test_sin_catalogo_no_inventa_cuentas(self):
        CuentaContable.objects.all().delete()
        datos = self.consultar('31/07/2020 Pago de gastos operativos por S/ 20,000 al contado').json()
        self.assertEqual(datos['estado'], 'requiere_aclaracion')
        self.assertNotIn('contrapartida', datos['datos_detectados'])
        self.assertNotIn('(62)', datos['pregunta'])

    def test_varias_cuentas_de_efectivo_no_elige_una_arbitrariamente(self):
        CuentaContable.objects.create(codigo='CAJ', nombre='Caja', tipo='activo')
        datos = self.consultar('31/07/2020 Pago de gastos operativos por S/ 20,000 al contado').json()
        self.assertEqual(datos['datos_detectados']['forma_pago'], 'al contado')
        self.assertNotIn('contrapartida', datos['datos_detectados'])

    def test_sin_fecha_conserva_importe_y_no_inventa_fecha(self):
        datos = self.consultar('Se pagan gastos operativos por S/ 20,000 al contado').json()
        self.assertEqual(datos['estado'], 'requiere_aclaracion')
        self.assertEqual(datos['datos_detectados']['importe'], '20000.00')
        self.assertNotIn('fecha', datos['datos_detectados'])
        self.assertEqual(datos['datos_faltantes'], ['tipo_gasto_operativo', 'fecha'])

    def test_aclaracion_del_proveedor_conserva_datos_locales(self):
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Qué servicio se pagó?',
            'motivo': 'Falta el servicio.', 'datos_detectados': {'fecha': '2026-01-01'},
            'datos_faltantes': ['tipo_servicio'],
        })
        datos = generar_propuesta('31/07/2020 Se pagan servicios por S/ 20,000 al contado', self.proveedor)
        self.assertEqual(datos['datos_detectados']['fecha'], '2020-07-31')
        self.assertEqual(datos['datos_detectados']['importe'], '20000.00')
        self.assertEqual(datos['datos_detectados']['contrapartida']['cuenta_codigo'], '10')
        self.assertEqual(datos['datos_faltantes'], ['tipo_servicio'])

    def test_fallo_real_de_transporte_sigue_siendo_502(self):
        with patch.dict('os.environ', {'GROQ_API_KEY': 'clave-prueba'}), patch(
                'core.services.chatbot.requests.post', side_effect=requests.Timeout):
            respuesta = self.client.post(reverse('chatbot_api'), {
                'message': '31/07/2020 Pago de gastos de personal por S/ 20,000 al contado'})
        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(respuesta.json()['status'], 'error')

    def test_respuesta_imposible_de_procesar_sigue_siendo_502(self):
        self.proveedor.completar.return_value = 'JSON inválido'
        respuesta = self.consultar('31/07/2020 Pago de tributos por S/ 20,000 al contado')
        self.assertEqual(respuesta.status_code, 502)
