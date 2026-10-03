from django.test import TestCase
from django.urls import reverse

from .models import CuentaContable


class PantallaCuentasTests(TestCase):
    def test_error_de_codigo_duplicado_conserva_datos_y_no_modifica_la_cuenta(self):
        cuenta = CuentaContable.objects.create(codigo='10', nombre='Caja', tipo='activo')
        datos = {
            'codigo': '10', 'nombre': 'Cuenta "especial" <script>',
            'tipo': 'activo', 'subcategoria': 'existencias',
        }
        respuesta = self.client.post(reverse('gestionar_cuentas'), datos)
        self.assertEqual(respuesta.status_code, 200)
        self.assertEqual(dict(respuesta.context['formulario'].items()), datos)
        self.assertContains(respuesta, 'value="Cuenta &quot;especial&quot; &lt;script&gt;"')
        self.assertContains(respuesta, 'value="activo" selected')
        self.assertContains(respuesta, 'value="existencias" selected')
        cuenta.refresh_from_db()
        self.assertEqual(cuenta.nombre, 'Caja')
        self.assertEqual(CuentaContable.objects.count(), 1)

    def test_catalogo_vacio_muestra_acceso_para_crear_primera_cuenta(self):
        respuesta = self.client.get(reverse('gestionar_cuentas'))
        self.assertContains(respuesta, 'Crear primera cuenta')
        self.assertContains(respuesta, 'js/plan_cuentas.js')
        self.assertNotContains(respuesta, 'data-cuenta data-codigo=')
