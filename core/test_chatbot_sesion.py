import json
from unittest.mock import Mock, patch

from django.test import Client, TestCase
from django.urls import reverse

from core.models import AsientoContable, CuentaContable, Movimiento
from core.plan_cuentas import PLAN_CUENTAS
from core.services.aclaracion_sesion import CLAVE_ACLARACION


class AclaracionSesionTests(TestCase):
    gasto = '31/07/2020 Se pagan gastos operativos por 20,000 soles al contado'

    def setUp(self):
        CuentaContable.objects.bulk_create([
            CuentaContable(codigo=c, nombre=n, tipo=t, subcategoria=s)
            for c, n, t, s in PLAN_CUENTAS
        ])
        self.proveedor = Mock()
        parche = patch('core.services.chatbot.ProveedorGroq', return_value=self.proveedor)
        parche.start()
        self.addCleanup(parche.stop)

    def consultar(self, mensaje, cliente=None):
        respuesta = (cliente or self.client).post(reverse('chatbot_api'), {'message': mensaje})
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    def duda(self, campo, pregunta, datos=None):
        return json.dumps({'estado': 'requiere_aclaracion', 'pregunta': pregunta,
                           'datos_detectados': datos or {}, 'datos_faltantes': [campo]})

    def propuesta(self, debe, haber, importe):
        return json.dumps({'estado': 'propuesta', 'fecha': '2026-10-02', 'descripcion': 'Operación aclarada',
                           'movimientos': [{'cuenta_codigo': debe, 'tipo': 'debe', 'monto': importe},
                                           {'cuenta_codigo': haber, 'tipo': 'haber', 'monto': importe}]})

    def comprobar_gasto(self, respuesta, codigo):
        inicial = self.consultar(self.gasto)
        self.assertEqual(inicial['estado'], 'requiere_aclaracion')
        pendiente = self.client.session[CLAVE_ACLARACION]
        self.assertEqual(pendiente['mensaje_original'], self.gasto)
        self.assertEqual(pendiente['datos_detectados']['operacion'], 'pago de gasto')
        final = self.consultar(respuesta)
        self.assertEqual(final['estado'], 'propuesta')
        self.assertEqual(final['fecha'], '2020-07-31')
        self.assertEqual(final['movimientos'], [
            {'cuenta_codigo': codigo, 'tipo': 'debe', 'monto': '20000.00'},
            {'cuenta_codigo': '10', 'tipo': 'haber', 'monto': '20000.00'},
        ])
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)
        self.proveedor.completar.assert_not_called()
        self.assertFalse(AsientoContable.objects.exists())
        self.assertFalse(Movimiento.objects.exists())

    def test_gasto_terceros(self):
        self.comprobar_gasto('terceros', '63')

    def test_gasto_personal(self):
        self.comprobar_gasto('personal', '62')

    def test_gasto_tributos(self):
        self.comprobar_gasto('tributos', '64')

    def test_gasto_la_63(self):
        self.comprobar_gasto('la 63', '63')

    def test_gasto_cuenta_63(self):
        self.comprobar_gasto('cuenta 63', '63')

    def test_gasto_servicios_de_terceros(self):
        self.comprobar_gasto('servicios de terceros', '63')

    def test_gasto_otros_gastos(self):
        self.comprobar_gasto('otros gastos', '65')

    def comprobar_condicion(self, original, respuesta, operacion, debe, haber, importe):
        self.proveedor.completar.return_value = self.duda('forma_pago', '¿Fue al contado o al crédito?')
        self.consultar(original)
        self.proveedor.completar.return_value = self.propuesta(debe, haber, importe)
        final = self.consultar(respuesta)
        self.assertEqual(final['estado'], 'propuesta')
        self.assertEqual(final['fecha'], '2020-07-31')
        sistema = self.proveedor.completar.call_args.args[0][0]['content']
        contexto = json.loads(sistema.split('CONTINUACIÓN DE ACLARACIÓN: ')[1])
        self.assertEqual(contexto['mensaje_original'], original)
        self.assertEqual(contexto['respuesta_nueva_usuario'], respuesta)
        self.assertEqual(contexto['dato_pendiente'], ['forma_pago'])
        self.assertEqual(contexto['datos_detectados']['operacion'], operacion)
        self.assertEqual(contexto['datos_detectados']['importe'], importe)
        self.assertEqual(contexto['datos_detectados']['forma_pago'],
                         'al crédito' if 'crédito' in respuesta else 'al contado')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)

    def test_compra_credito(self):
        self.comprobar_condicion('31/07/2020 Se compra mercadería por 5,000', 'crédito', 'compra',
                                '60', '42', '5000.00')

    def test_venta_contado(self):
        self.comprobar_condicion('31/07/2020 Se realiza una venta por 10,000', 'contado', 'venta',
                                '10', '70', '10000.00')

    def test_venta_al_credito(self):
        self.comprobar_condicion('31/07/2020 Se realiza una venta por 10,000', 'al crédito', 'venta',
                                '12', '70', '10000.00')

    def test_aclaracion_varios_turnos(self):
        self.consultar('Se pagan gastos operativos por 20,000 soles al contado')
        segunda = self.consultar('terceros')
        self.assertEqual(segunda['datos_faltantes'], ['fecha'])
        self.assertNotIn('importe', segunda['pregunta'])
        final = self.consultar('31/07/2020')
        self.assertEqual(final['estado'], 'propuesta')
        self.assertEqual(final['fecha'], '2020-07-31')
        self.assertEqual(final['movimientos'][0]['cuenta_codigo'], '63')

    def test_respuesta_ambigua_conserva_datos(self):
        self.consultar(self.gasto)
        for respuesta in ['no sé', 'personal o terceros', 'no personal']:
            duda = self.consultar(respuesta)
            self.assertEqual(duda['estado'], 'requiere_aclaracion')
            self.assertEqual(duda['datos_faltantes'], ['tipo_gasto_operativo'])
            self.assertEqual(duda['datos_detectados']['fecha'], '2020-07-31')
            self.assertEqual(duda['datos_detectados']['importe'], '20000.00')
        self.assertEqual(self.consultar('terceros')['estado'], 'propuesta')

    def test_nuevo_hecho_reemplaza_aclaracion(self):
        self.consultar(self.gasto)
        nuevo = '01/08/2020 Se realiza una venta por 10,000 al contado'
        self.proveedor.completar.return_value = self.propuesta('10', '70', '10000.00')
        final = self.consultar(nuevo)
        self.assertEqual(final['fecha'], '2020-08-01')
        self.assertEqual(final['movimientos'][0]['monto'], '10000.00')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)
        self.assertEqual(self.proveedor.completar.call_args.args[0][1]['content'], nuevo)

    def test_nuevo_hecho_reemplaza_con_otra_aclaracion(self):
        self.consultar(self.gasto)
        nuevo = '01/08/2020 Se compra mercadería por 5,000'
        self.proveedor.completar.return_value = self.duda('forma_pago', '¿Fue al contado o al crédito?')
        self.consultar(nuevo)
        pendiente = self.client.session[CLAVE_ACLARACION]
        self.assertEqual(pendiente['mensaje_original'], nuevo)
        self.assertEqual(pendiente['datos_detectados']['importe'], '5000.00')
        self.assertNotIn('contrapartida', pendiente['datos_detectados'])

    def test_dos_sesiones_no_comparten_contexto(self):
        self.consultar(self.gasto)
        otro = Client()
        self.proveedor.completar.return_value = self.duda('informacion_contable', '¿Qué operación desea registrar?')
        self.consultar('terceros', otro)
        self.assertEqual(otro.session[CLAVE_ACLARACION]['mensaje_original'], 'terceros')
        self.assertNotIn('importe', otro.session[CLAVE_ACLARACION]['datos_detectados'])
        self.assertEqual(self.consultar('personal')['movimientos'][0]['cuenta_codigo'], '62')
        self.assertIn(CLAVE_ACLARACION, otro.session)

    def test_cancelacion(self):
        self.consultar(self.gasto)
        self.assertEqual(self.consultar('cancelar')['estado'], 'cancelado')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)

    def test_caducidad(self):
        self.consultar(self.gasto)
        sesion = self.client.session
        sesion[CLAVE_ACLARACION]['actualizada_en'] -= 1801
        sesion.save()
        self.proveedor.completar.return_value = self.duda('informacion_contable', '¿Qué operación desea registrar?')
        self.consultar('terceros')
        self.assertEqual(self.client.session[CLAVE_ACLARACION]['mensaje_original'], 'terceros')

    def test_catalogo_personalizado(self):
        CuentaContable.objects.all().delete()
        CuentaContable.objects.create(codigo='CAJ', nombre='Caja', tipo='activo')
        CuentaContable.objects.create(codigo='EXT', nombre='Servicios de terceros', tipo='gasto')
        self.consultar(self.gasto)
        final = self.consultar('terceros')
        self.assertEqual([m['cuenta_codigo'] for m in final['movimientos']], ['EXT', 'CAJ'])

    def test_cuenta_ausente_no_se_inventa(self):
        self.consultar(self.gasto)
        CuentaContable.objects.filter(codigo='63').delete()
        duda = self.consultar('la 63')
        self.assertEqual(duda['estado'], 'requiere_aclaracion')
        self.assertNotIn('tipo_gasto_operativo', duda['datos_detectados'])

    def test_dos_opciones_coincidentes_requieren_aclaracion(self):
        CuentaContable.objects.create(codigo='631', nombre='Servicios de terceros locales', tipo='gasto')
        self.consultar(self.gasto)
        duda = self.consultar('terceros')
        self.assertEqual(duda['estado'], 'requiere_aclaracion')
        self.assertNotIn('tipo_gasto_operativo', duda['datos_detectados'])
        self.assertEqual(self.consultar('cuenta 63')['movimientos'][0]['cuenta_codigo'], '63')

    def test_opcion_de_cuenta_en_otra_pregunta_llega_al_modelo(self):
        original = '31/07/2020 Se realiza una venta por 10,000 al contado'
        self.proveedor.completar.return_value = self.duda(
            'cuenta_ingreso', '¿Qué cuenta de ingreso corresponde: Ventas (70) u otra?')
        self.consultar(original)
        self.proveedor.completar.return_value = self.propuesta('10', '70', '10000.00')
        self.assertEqual(self.consultar('ventas')['estado'], 'propuesta')
        sistema = self.proveedor.completar.call_args.args[0][0]['content']
        contexto = json.loads(sistema.split('CONTINUACIÓN DE ACLARACIÓN: ')[1])
        self.assertEqual(contexto['datos_detectados']['cuenta_ingreso']['cuenta_codigo'], '70')

    def test_varios_turnos_de_otro_tipo_con_contexto_explicito(self):
        original = 'Se realiza una venta por 10,000'
        self.proveedor.completar.return_value = self.duda('forma_pago', '¿Fue al contado o al crédito?')
        self.consultar(original)
        self.proveedor.completar.return_value = self.duda('fecha', '¿En qué fecha ocurrió?')
        segunda = self.consultar('al crédito')
        self.assertEqual(segunda['datos_detectados']['importe'], '10000.00')
        self.assertEqual(segunda['datos_detectados']['forma_pago'], 'al crédito')
        self.proveedor.completar.return_value = self.propuesta('12', '70', '10000.00')
        final = self.consultar('31/07/2020')
        self.assertEqual(final['estado'], 'propuesta')
        sistema = self.proveedor.completar.call_args.args[0][0]['content']
        contexto = json.loads(sistema.split('CONTINUACIÓN DE ACLARACIÓN: ')[1])
        self.assertEqual(contexto['contexto']['forma_pago'], 'al crédito')
        self.assertEqual(contexto['datos_detectados']['importe'], '10000.00')
        self.assertEqual(contexto['datos_detectados']['forma_pago'], 'al crédito')

    def test_error_proveedor_conserva_aclaracion(self):
        self.proveedor.completar.return_value = self.duda('forma_pago', '¿Fue al contado o al crédito?')
        self.consultar('31/07/2020 Se compra mercadería por 5,000')
        self.proveedor.completar.return_value = 'inválido'
        respuesta = self.client.post(reverse('chatbot_api'), {'message': 'crédito'})
        self.assertEqual(respuesta.status_code, 502)
        self.assertEqual(self.client.session[CLAVE_ACLARACION]['datos_detectados']['importe'], '5000.00')

    def test_datos_decimales_del_modelo_son_serializables_en_sesion(self):
        self.proveedor.completar.return_value = self.duda(
            'tratamiento_impuesto', '¿El importe incluye impuesto?', {'impuesto': 1800.50})
        self.consultar('31/07/2020 Se realiza una venta por 10,000')
        self.assertEqual(self.client.session[CLAVE_ACLARACION]['datos_detectados']['impuesto'], '1800.5')
