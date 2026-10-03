import json
from unittest.mock import Mock, patch

from django.test import TestCase
from django.urls import reverse

from core.models import AsientoContable, CuentaContable, Movimiento
from core.plan_cuentas import PLAN_CUENTAS
from core.services.aclaracion_sesion import CLAVE_ACLARACION


class OpcionesAclaracionTests(TestCase):
    inventario = 'En el inventario se observa un saldo final de 10,000 soles al cierre del mes.'
    gasto = '31/07/2020 Se pagan gastos operativos por 20,000 soles al contado'

    def setUp(self):
        CuentaContable.objects.bulk_create([
            CuentaContable(codigo=c, nombre=n, tipo=t, subcategoria=s)
            for c, n, t, s in PLAN_CUENTAS
        ])
        asiento = AsientoContable.objects.create(fecha='2020-07-20', descripcion='Compra de mercaderías')
        for codigo, tipo in [('20', 'debe'), ('10', 'haber')]:
            Movimiento.objects.create(asiento=asiento, cuenta=CuentaContable.objects.get(codigo=codigo),
                                      tipo=tipo, monto='50000')
        self.proveedor = Mock()
        parche = patch('core.services.chatbot.ProveedorGroq', return_value=self.proveedor)
        parche.start()
        self.addCleanup(parche.stop)

    def consultar(self, mensaje):
        respuesta = self.client.post(reverse('chatbot_api'), {'message': mensaje})
        self.assertEqual(respuesta.status_code, 200, respuesta.content)
        return respuesta.json()

    def comprobar_contexto(self, anterior):
        posterior = self.client.session[CLAVE_ACLARACION]
        for campo in ('mensaje_original', 'pregunta_pendiente', 'datos_detectados',
                      'datos_faltantes', 'contexto'):
            self.assertEqual(posterior[campo], anterior[campo])

    def test_inventario_consulta_catalogo_y_mantiene_contexto(self):
        inicial = self.consultar(self.inventario)
        self.assertEqual(inicial['datos_faltantes'], ['cuenta_inventario'])
        pendiente = self.client.session[CLAVE_ACLARACION]
        respuesta = self.consultar('¿Qué inventarios hay?')
        self.assertEqual(respuesta['estado'], 'informativo')
        self.assertIn('20 - Mercaderías', respuesta['response'])
        self.assertIn('29 - Desvalorización de Existencias', respuesta['response'])
        self.assertIn('¿Cuál corresponde al saldo final de S/ 10,000.00?', respuesta['response'])
        self.assertNotIn('movimientos', respuesta)
        self.assertNotIn('revision_url', respuesta)
        self.comprobar_contexto(pendiente)
        self.proveedor.completar.assert_not_called()

    def test_variantes_de_preguntas_informativas(self):
        self.consultar(self.inventario)
        pendiente = self.client.session[CLAVE_ACLARACION]
        for mensaje in ['¿qué opciones tengo?', '¿qué cuentas existen?',
                        '¿cuáles son las cuentas de inventario?', 'muéstrame las opciones']:
            with self.subTest(mensaje=mensaje):
                respuesta = self.consultar(mensaje)
                self.assertEqual(respuesta['estado'], 'informativo')
                self.assertIn('20 - Mercaderías', respuesta['response'])
                self.comprobar_contexto(pendiente)
        self.proveedor.completar.assert_not_called()

    def test_gasto_opciones_y_propuesta_limpia_contexto(self):
        self.consultar(self.gasto)
        pendiente = self.client.session[CLAVE_ACLARACION]
        respuesta = self.consultar('¿Qué tipos de gasto hay?')
        esperadas = list(CuentaContable.objects.filter(tipo='gasto').values_list('codigo', flat=True))
        self.assertEqual([o['cuenta_codigo'] for o in respuesta['opciones']], esperadas)
        self.assertIn('63 - Gastos de Servicios Prestados por Terceros', respuesta['response'])
        self.comprobar_contexto(pendiente)
        final = self.consultar('cuenta 63')
        self.assertEqual(final['estado'], 'propuesta')
        self.assertEqual(final['fecha'], '2020-07-31')
        self.assertEqual(final['movimientos'][0]['cuenta_codigo'], '63')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)
        self.proveedor.completar.assert_not_called()
        self.assertEqual(AsientoContable.objects.count(), 1)

    def test_forma_pago_opciones_y_continuacion(self):
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'requiere_aclaracion', 'pregunta': '¿Fue al contado o al crédito?',
            'datos_faltantes': ['forma_pago'], 'datos_detectados': {}})
        original = '31/07/2020 Se realiza una venta por 10,000'
        self.consultar(original)
        pendiente = self.client.session[CLAVE_ACLARACION]
        respuesta = self.consultar('¿Qué opciones tengo?')
        self.assertIn('«al contado» o «al crédito»', respuesta['response'])
        self.assertIn('10 - Efectivo y Equivalentes de Efectivo', respuesta['response'])
        self.comprobar_contexto(pendiente)
        self.proveedor.completar.assert_called_once()
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'propuesta', 'fecha': '2020-07-31', 'descripcion': 'Venta',
            'movimientos': [{'cuenta_codigo': '12', 'tipo': 'debe', 'monto': '10000'},
                            {'cuenta_codigo': '70', 'tipo': 'haber', 'monto': '10000'}]})
        final = self.consultar('al crédito')
        self.assertEqual(final['estado'], 'propuesta')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)

    def comprobar_eleccion_inventario(self, respuesta, codigo):
        self.consultar(self.inventario)
        self.consultar('¿Qué inventarios hay?')
        final = self.consultar(respuesta)
        self.assertEqual(final['estado'], 'requiere_aclaracion')
        self.assertNotIn('cuenta_inventario', final['datos_faltantes'])
        self.assertEqual(final['datos_detectados']['cuenta_inventario']['cuenta_codigo'], codigo)
        self.assertEqual(final['datos_detectados']['cuentas_inventario'], [codigo])
        self.assertEqual(final['datos_detectados']['inventario_final_informado'], '10000.00')
        self.assertEqual(self.client.session[CLAVE_ACLARACION]['mensaje_original'], self.inventario)
        if codigo == '20':
            self.assertEqual(final['datos_detectados']['diferencia'], '40000.00')
            self.assertEqual(final['datos_faltantes'], ['causa_ajuste'])
        self.proveedor.completar.assert_not_called()

    def test_respuesta_codigo(self):
        self.comprobar_eleccion_inventario('20', '20')

    def test_respuesta_cuenta_codigo(self):
        self.comprobar_eleccion_inventario('cuenta 20', '20')

    def test_respuesta_nombre(self):
        self.comprobar_eleccion_inventario('Mercaderías', '20')

    def test_respuesta_productos_terminados(self):
        self.comprobar_eleccion_inventario('productos terminados', '21')

    def test_respuesta_materias_primas(self):
        self.comprobar_eleccion_inventario('materias primas', '24')

    def test_dos_consultas_seguidas_y_respuesta_nombre(self):
        self.consultar(self.gasto)
        pendiente = self.client.session[CLAVE_ACLARACION]
        for mensaje in ['¿Qué tipos de gasto hay?', 'muéstrame las opciones']:
            self.assertEqual(self.consultar(mensaje)['estado'], 'informativo')
            self.comprobar_contexto(pendiente)
        self.assertEqual(self.consultar('servicios de terceros')['estado'], 'propuesta')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)

    def test_opciones_consultan_catalogo_actual_personalizado(self):
        self.consultar(self.inventario)
        Movimiento.objects.all().delete()
        CuentaContable.objects.all().delete()
        CuentaContable.objects.create(codigo='INV', nombre='Productos del almacén', tipo='activo',
                                     subcategoria='existencias')
        respuesta = self.consultar('¿Qué inventarios hay?')
        self.assertEqual(respuesta['opciones'], [
            {'cuenta_codigo': 'INV', 'cuenta_nombre': 'Productos del almacén'}])
        self.assertNotIn('20 -', respuesta['response'])
        self.assertEqual(self.consultar('INV')['datos_detectados']['cuenta_inventario']['cuenta_codigo'], 'INV')

    def test_catalogo_vacio_no_inventa_opciones(self):
        self.consultar(self.inventario)
        pendiente = self.client.session[CLAVE_ACLARACION]
        Movimiento.objects.all().delete()
        CuentaContable.objects.all().delete()
        respuesta = self.consultar('¿Qué inventarios hay?')
        self.assertEqual(respuesta['opciones'], [])
        self.assertIn('No hay cuentas de inventario disponibles', respuesta['response'])
        self.comprobar_contexto(pendiente)

    def test_nuevo_hecho_despues_de_consulta_reemplaza_contexto(self):
        self.consultar(self.inventario)
        self.consultar('¿Qué inventarios hay?')
        nuevo = '01/08/2020 Se pagan gastos operativos por 200 soles al contado'
        self.consultar(nuevo)
        pendiente = self.client.session[CLAVE_ACLARACION]
        self.assertEqual(pendiente['mensaje_original'], nuevo)
        self.assertEqual(pendiente['datos_faltantes'], ['tipo_gasto_operativo'])
        self.assertNotIn('inventario_final_informado', pendiente['datos_detectados'])

    def test_inventario_propuesta_final_limpia_contexto(self):
        self.consultar(self.inventario)
        self.consultar('¿Qué inventarios hay?')
        self.consultar('Mercaderías')
        self.proveedor.completar.return_value = json.dumps({
            'estado': 'propuesta', 'fecha': '2020-07-31', 'descripcion': 'Costo de ventas',
            'movimientos': [{'cuenta_codigo': '69', 'tipo': 'debe', 'monto': '40000'},
                            {'cuenta_codigo': '20', 'tipo': 'haber', 'monto': '40000'}]})
        final = self.consultar('Registrar la diferencia como costo de ventas')
        self.assertEqual(final['estado'], 'propuesta', final)
        self.assertEqual(final['movimientos'][1]['monto'], '40000.00')
        self.assertNotIn(CLAVE_ACLARACION, self.client.session)
        self.assertEqual(AsientoContable.objects.count(), 1)
