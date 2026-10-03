"""
Vistas del Sistema Contable.

Cada vista implementa una funcionalidad específica:
- index: Menú principal con resumen
- gestionar_cuentas: CRUD del catálogo de cuentas contables
- registrar_asiento: Formulario dinámico para crear asientos
- libro_diario: Reporte de todos los asientos por fecha
- libro_mayor: Movimientos agrupados por cuenta con saldos
- balance_comprobacion: Verificación de cuadre (Debe == Haber)
- estado_resultados: Cálculo de utilidad/pérdida
- balance_general: Activo = Pasivo + Patrimonio
"""
import os
import json
import time
import uuid
import gc
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.db.models import Sum
from decimal import Decimal
from django.db import transaction
from django.conf import settings
from django.core.mail import EmailMessage
from django.template.loader import render_to_string
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from xhtml2pdf import pisa
from io import BytesIO
from .models import CuentaContable, AsientoContable, Movimiento
from .reporte_utils import get_reporte_context
from .services.asientos import validar_asiento_formulario
from .services.chatbot import ErrorChatbot, generar_propuesta, preparar_revision, texto_respuesta, informar_opciones
from .services.aclaracion_sesion import (CLAVE_ACLARACION, obtener_pendiente, guardar_pendiente,
                                        nuevo_hecho_completo, resolver_respuesta, consulta_opciones)


# ─── PÁGINA PRINCIPAL ──────────────────────────────────────────────────────────

def index(request):
    """
    Muestra el menú principal con un resumen del estado del sistema:
    total de cuentas, asientos, y totales de Debe/Haber.
    """
    total_asientos = AsientoContable.objects.count()
    total_cuentas = CuentaContable.objects.count()
    total_movimientos = Movimiento.objects.count()

    # Calcular totales generales
    total_debe = Movimiento.objects.filter(tipo='debe').aggregate(
        total=Sum('monto'))['total'] or Decimal('0')
    total_haber = Movimiento.objects.filter(tipo='haber').aggregate(
        total=Sum('monto'))['total'] or Decimal('0')

    # Últimos 5 asientos registrados (ordenados por el momento en que se crearon en el sistema)
    ultimos_asientos = AsientoContable.objects.prefetch_related(
        'movimientos__cuenta'
    ).order_by('-created_at')[:5]

    context = {
        'total_asientos': total_asientos,
        'total_cuentas': total_cuentas,
        'total_movimientos': total_movimientos,
        'total_debe': total_debe,
        'total_haber': total_haber,
        'ultimos_asientos': ultimos_asientos,
    }
    return render(request, 'index.html', context)


# ─── GESTIÓN DE CUENTAS CONTABLES ──────────────────────────────────────────────

def gestionar_cuentas(request):
    """
    Permite crear nuevas cuentas contables especificando código, nombre, tipo
    y subcategoría (incluida la clasificación en el Estado de Resultados).
    También muestra la lista completa del catálogo de cuentas.
    """
    if request.method == 'POST':
        codigo = request.POST.get('codigo', '').strip()
        nombre = request.POST.get('nombre', '').strip()
        tipo = request.POST.get('tipo', '').strip()
        subcategoria = request.POST.get('subcategoria', '').strip()

        errors = []
        if not codigo:
            errors.append('El código es obligatorio.')
        if not nombre:
            errors.append('El nombre es obligatorio.')
        if tipo not in dict(CuentaContable.TIPO_CHOICES):
            errors.append('El tipo de cuenta no es válido.')
        if subcategoria and subcategoria not in CuentaContable.SUBCATEGORIAS_POR_TIPO.get(tipo, []):
            errors.append('La subcategoría no es válida para este tipo de cuenta.')
        if CuentaContable.objects.filter(codigo=codigo).exists():
            errors.append(f'Ya existe una cuenta con el código "{codigo}".')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            CuentaContable.objects.create(
                codigo=codigo, nombre=nombre, tipo=tipo, subcategoria=subcategoria
            )
            messages.success(request, f'Cuenta "{codigo} - {nombre}" creada exitosamente.')
            return redirect('gestionar_cuentas')

    cuentas = CuentaContable.objects.all()
    context = {
        'cuentas': cuentas,
        'tipos': CuentaContable.TIPO_CHOICES,
        'subcategorias': CuentaContable.SUBCATEGORIA_CHOICES,
        'subcategorias_por_tipo': CuentaContable.SUBCATEGORIAS_POR_TIPO,
        'formulario': request.POST if request.method == 'POST' else {},
    }
    return render(request, 'gestionar_cuentas.html', context)


def eliminar_cuenta(request, cuenta_id):
    """
    Elimina una cuenta contable solo si no tiene movimientos asociados.
    Si tiene movimientos, muestra un mensaje de error.
    """
    cuenta = get_object_or_404(CuentaContable, id=cuenta_id)
    if cuenta.movimientos.exists():
        messages.error(
            request,
            f'No se puede eliminar "{cuenta}" porque tiene movimientos asociados.'
        )
    else:
        messages.success(request, f'Cuenta "{cuenta}" eliminada exitosamente.')
        cuenta.delete()
    return redirect('gestionar_cuentas')


# ─── REGISTRO DE ASIENTOS CONTABLES ────────────────────────────────────────────

PROPUESTAS_SESION = 'chatbot_propuestas'
PROPUESTA_TTL = 30 * 60


def _propuestas_vigentes(request):
    ahora = time.time()
    return {
        identificador: propuesta
        for identificador, propuesta in request.session.get(PROPUESTAS_SESION, {}).items()
        if 0 <= ahora - propuesta['creada_en'] < PROPUESTA_TTL
    }


def _formulario_enviado(datos):
    try:
        cantidad = max(0, min(int(datos.get('num_movimientos', 0)), 1000))
    except (ValueError, TypeError):
        cantidad = 0
    return {
        'fecha': datos.get('fecha', ''), 'descripcion': datos.get('descripcion', ''),
        'movimientos': [
            {'cuenta_id': datos.get(f'cuenta_{i}', ''), 'tipo': datos.get(f'tipo_{i}', ''),
             'monto': datos.get(f'monto_{i}', '')}
            for i in range(cantidad)
        ],
    }


def registrar_asiento(request):
    """
    Formulario dinámico para registrar asientos contables.
    Procesa múltiples líneas de movimiento (mínimo 2).
    Valida que la suma del Debe sea igual a la del Haber antes de guardar.
    """
    cuentas = CuentaContable.objects.all()

    if not cuentas.exists():
        messages.warning(
            request,
            'Debe crear al menos una cuenta contable antes de registrar asientos.'
        )
        return redirect('gestionar_cuentas')

    inicial = {'fecha': '', 'descripcion': '', 'movimientos': []}
    propuesta_id = request.GET.get('propuesta', '')
    if request.method == 'GET' and propuesta_id:
        propuestas = _propuestas_vigentes(request)
        propuesta = propuestas.get(propuesta_id)
        if propuesta is None:
            messages.warning(request, 'La propuesta no existe en esta sesión o ha caducado.')
            return redirect('registrar_asiento')
        try:
            revision = preparar_revision(propuesta['resultado'])
        except ErrorChatbot as exc:
            propuestas.pop(propuesta_id, None)
            request.session[PROPUESTAS_SESION] = propuestas
            messages.error(request, str(exc) + ' ' + ' '.join(exc.errores))
            return redirect('registrar_asiento')
        inicial.update(fecha=revision['fecha'], descripcion=revision['descripcion'], movimientos=revision['movimientos'])

    if request.method == 'POST':
        inicial = _formulario_enviado(request.POST)
        fecha = request.POST.get('fecha', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        movimientos_data, errors = validar_asiento_formulario(request.POST)

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            with transaction.atomic():
                # Crear el asiento y sus movimientos en la base de datos
                asiento = AsientoContable.objects.create(
                    fecha=fecha,
                    descripcion=descripcion,
                )
                for m in movimientos_data:
                    Movimiento.objects.create(
                        asiento=asiento,
                        cuenta=m['cuenta'],
                        tipo=m['tipo'],
                        monto=m['monto'],
                    )

            if propuesta_id:
                propuestas = _propuestas_vigentes(request)
                propuestas.pop(propuesta_id, None)
                request.session[PROPUESTAS_SESION] = propuestas

            # --- MENSAJE CON HORA REAL ---
            hora_real = timezone.localtime(timezone.now()).strftime("%d/%m/%Y a las %H:%M")
            messages.success(
                request,
                f'Asiento registrado exitosamente el {hora_real}.'
            )
            return redirect('libro_diario')

    # Para el formulario mostramos los últimos creados
    asientos_registrados = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('-created_at')

    context = {
        'cuentas': cuentas,
        'asientos_registrados': asientos_registrados,
        'formulario_inicial': inicial,
        'propuesta_id': propuesta_id,
        'cuentas_json': [{'id': c.pk, 'text': f'{c.codigo} - {c.nombre}'} for c in cuentas],
    }
    return render(request, 'registrar_asiento.html', context)


# ─── LIBRO DIARIO ──────────────────────────────────────────────────────────────

def libro_diario(request):
    """
    Muestra todos los asientos contables ordenados cronológicamente.
    Cada asiento se despliega con sus movimientos al Debe y al Haber.
    """
    # --- ORDEN CRONOLÓGICO ESTRICTO ---
    asientos = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id')
    cuentas = CuentaContable.objects.all()
    
    context = {
        'asientos': asientos,
        'cuentas': cuentas,
    }
    return render(request, 'libro_diario.html', context)


# ─── LIBRO MAYOR ───────────────────────────────────────────────────────────────

def libro_mayor(request):
    """
    Agrupa los movimientos por cuenta contable.
    Para cada cuenta muestra:
    - Todos sus movimientos con fecha y asiento
    - Total Debe, Total Haber
    - Saldo calculado según la naturaleza de la cuenta
    """
    cuentas = CuentaContable.objects.all()

    datos_cuentas = []
    for cuenta in cuentas:
        # ORDEN CRONOLÓGICO EN EL MAYOR
        movimientos = cuenta.movimientos.select_related('asiento').order_by('asiento__fecha', 'asiento__id')
        if not movimientos.exists():
            continue

        total_debe = movimientos.filter(tipo='debe').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        total_haber = movimientos.filter(tipo='haber').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')

        # Saldo según naturaleza de la cuenta
        if cuenta.naturaleza_deudora:
            saldo = total_debe - total_haber
        else:
            saldo = total_haber - total_debe

        datos_cuentas.append({
            'cuenta': cuenta,
            'movimientos': movimientos,
            'total_debe': total_debe,
            'total_haber': total_haber,
            'saldo': saldo,
        })

    context = {
        'datos_cuentas': datos_cuentas,
    }
    return render(request, 'libro_mayor.html', context)


# ─── BALANCE DE COMPROBACIÓN ───────────────────────────────────────────────────

def balance_comprobacion(request):
    """
    Lista todas las cuentas con movimientos y verifica que los totales
    de Debe y Haber coincidan (el balance esté cuadrado).
    
    Muestra columnas de Sumas (Debe/Haber) y Saldos (Deudor/Acreedor).
    """
    cuentas = CuentaContable.objects.all()

    datos = []
    gran_total_debe = Decimal('0')
    gran_total_haber = Decimal('0')
    gran_saldo_deudor = Decimal('0')
    gran_saldo_acreedor = Decimal('0')

    for cuenta in cuentas:
        total_debe = cuenta.movimientos.filter(tipo='debe').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        total_haber = cuenta.movimientos.filter(tipo='haber').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')

        if total_debe == 0 and total_haber == 0:
            continue

        saldo = total_debe - total_haber
        saldo_deudor = saldo if saldo > 0 else Decimal('0')
        saldo_acreedor = abs(saldo) if saldo < 0 else Decimal('0')

        datos.append({
            'cuenta': cuenta,
            'total_debe': total_debe,
            'total_haber': total_haber,
            'saldo_deudor': saldo_deudor,
            'saldo_acreedor': saldo_acreedor,
        })

        gran_total_debe += total_debe
        gran_total_haber += total_haber
        gran_saldo_deudor += saldo_deudor
        gran_saldo_acreedor += saldo_acreedor

    context = {
        'datos': datos,
        'gran_total_debe': gran_total_debe,
        'gran_total_haber': gran_total_haber,
        'gran_saldo_deudor': gran_saldo_deudor,
        'gran_saldo_acreedor': gran_saldo_acreedor,
        'esta_cuadrado': gran_total_debe == gran_total_haber,
    }
    return render(request, 'balance_comprobacion.html', context)


# ─── ESTADO DE RESULTADOS (DETALLADO) ──────────────────────────────────────────

def estado_resultados(request):
    """
    Estado de Resultados con desglose completo.
    """
    def saldo_cuenta(cuenta):
        t_debe = cuenta.movimientos.filter(tipo='debe').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        t_haber = cuenta.movimientos.filter(tipo='haber').aggregate(
            total=Sum('monto'))['total'] or Decimal('0')
        if cuenta.tipo == 'gasto':
            return t_debe - t_haber
        else:  # ingreso
            return t_haber - t_debe

    def obtener_items(queryset):
        items = []
        total = Decimal('0')
        for c in queryset:
            s = saldo_cuenta(c)
            if s != 0:
                items.append({'cuenta': c, 'saldo': s})
                total += s
        return items, total

    ventas, total_ventas = obtener_items(
        CuentaContable.objects.filter(tipo='ingreso').exclude(subcategoria='otro_ingreso')
    )
    costo_ventas, total_costo_ventas = obtener_items(
        CuentaContable.objects.filter(tipo='gasto', subcategoria='costo_ventas')
    )
    utilidad_bruta = total_ventas - total_costo_ventas

    gastos_operativos, total_gastos_operativos = obtener_items(
        CuentaContable.objects.filter(tipo='gasto').exclude(
            subcategoria__in=['costo_ventas', 'gasto_financiero', 'otro_gasto']
        )
    )
    utilidad_operativa = utilidad_bruta - total_gastos_operativos

    gastos_financieros, total_gastos_financieros = obtener_items(
        CuentaContable.objects.filter(tipo='gasto', subcategoria='gasto_financiero')
    )
    otros_ingresos, total_otros_ingresos = obtener_items(
        CuentaContable.objects.filter(tipo='ingreso', subcategoria='otro_ingreso')
    )
    otros_gastos, total_otros_gastos = obtener_items(
        CuentaContable.objects.filter(tipo='gasto', subcategoria='otro_gasto')
    )

    utilidad_antes_impuesto = (
        utilidad_operativa
        - total_gastos_financieros
        + total_otros_ingresos
        - total_otros_gastos
    )

    tasa_impuesto = Decimal('30')
    if utilidad_antes_impuesto > 0:
        impuesto = (utilidad_antes_impuesto * tasa_impuesto / Decimal('100')).quantize(Decimal('0.01'))
    else:
        impuesto = Decimal('0')

    utilidad_neta = utilidad_antes_impuesto - impuesto

    context = {
        'ventas': ventas, 'total_ventas': total_ventas,
        'costo_ventas': costo_ventas, 'total_costo_ventas': total_costo_ventas,
        'utilidad_bruta': utilidad_bruta,
        'gastos_operativos': gastos_operativos, 'total_gastos_operativos': total_gastos_operativos,
        'utilidad_operativa': utilidad_operativa,
        'gastos_financieros': gastos_financieros, 'total_gastos_financieros': total_gastos_financieros,
        'otros_ingresos': otros_ingresos, 'total_otros_ingresos': total_otros_ingresos,
        'otros_gastos': otros_gastos, 'total_otros_gastos': total_otros_gastos,
        'utilidad_antes_impuesto': utilidad_antes_impuesto,
        'tasa_impuesto': tasa_impuesto,
        'impuesto': impuesto,
        'utilidad_neta': utilidad_neta,
    }
    return render(request, 'estado_resultados.html', context)


# ─── BALANCE GENERAL (ESTADO DE SITUACIÓN FINANCIERA) ──────────────────────────

def balance_general(request):
    """
    Estado de Situación Financiera con verificación de la ecuación contable.
    """
    def calcular_saldos_por_tipo(tipo_cuenta, deudora=True):
        cuentas = CuentaContable.objects.filter(tipo=tipo_cuenta)
        items = []
        total = Decimal('0')
        for cuenta in cuentas:
            t_debe = cuenta.movimientos.filter(tipo='debe').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            t_haber = cuenta.movimientos.filter(tipo='haber').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            saldo = (t_debe - t_haber) if deudora else (t_haber - t_debe)
            if saldo != 0:
                items.append({'cuenta': cuenta, 'saldo': saldo})
                total += saldo
        return items, total

    activos, total_activos = calcular_saldos_por_tipo('activo', deudora=True)
    pasivos, total_pasivos = calcular_saldos_por_tipo('pasivo', deudora=False)
    patrimonio, total_patrimonio = calcular_saldos_por_tipo('patrimonio', deudora=False)

    _, total_ingresos = calcular_saldos_por_tipo('ingreso', deudora=False)
    _, total_gastos = calcular_saldos_por_tipo('gasto', deudora=True)
    resultados_acumulados = total_ingresos - total_gastos  

    total_patrimonio_con_resultados = total_patrimonio + resultados_acumulados
    total_pasivo_patrimonio = total_pasivos + total_patrimonio_con_resultados
    esta_balanceado = total_activos == total_pasivo_patrimonio

    def totales_debe_haber(tipo_cuenta):
        cuentas = CuentaContable.objects.filter(tipo=tipo_cuenta)
        total_d = Decimal('0')
        total_h = Decimal('0')
        for c in cuentas:
            td = c.movimientos.filter(tipo='debe').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            th = c.movimientos.filter(tipo='haber').aggregate(
                total=Sum('monto'))['total'] or Decimal('0')
            total_d += td
            total_h += th
        return total_d, total_h

    activo_debe, activo_haber = totales_debe_haber('activo')
    pasivo_debe, pasivo_haber = totales_debe_haber('pasivo')
    patrimonio_debe, patrimonio_haber = totales_debe_haber('patrimonio')

    ecuacion_resumen = [
        {
            'concepto': 'ACTIVO',
            'debe': activo_debe, 'haber': activo_haber,
            'saldo_deudor': activo_debe - activo_haber if activo_debe >= activo_haber else Decimal('0'),
            'saldo_acreedor': activo_haber - activo_debe if activo_haber > activo_debe else Decimal('0'),
        },
        {
            'concepto': 'PASIVO',
            'debe': pasivo_debe, 'haber': pasivo_haber,
            'saldo_deudor': pasivo_debe - pasivo_haber if pasivo_debe >= pasivo_haber else Decimal('0'),
            'saldo_acreedor': pasivo_haber - pasivo_debe if pasivo_haber > pasivo_debe else Decimal('0'),
        },
        {
            'concepto': 'PATRIMONIO',
            'debe': patrimonio_debe, 'haber': patrimonio_haber,
            'saldo_deudor': patrimonio_debe - patrimonio_haber if patrimonio_debe >= patrimonio_haber else Decimal('0'),
            'saldo_acreedor': patrimonio_haber - patrimonio_debe if patrimonio_haber > patrimonio_debe else Decimal('0'),
        },
    ]
    ec_total_debe = sum(e['debe'] for e in ecuacion_resumen)
    ec_total_haber = sum(e['haber'] for e in ecuacion_resumen)
    ec_total_deudor = sum(e['saldo_deudor'] for e in ecuacion_resumen)
    ec_total_acreedor = sum(e['saldo_acreedor'] for e in ecuacion_resumen)

    context = {
        'activos': activos, 'pasivos': pasivos, 'patrimonio': patrimonio,
        'total_activos': total_activos, 'total_pasivos': total_pasivos,
        'total_patrimonio': total_patrimonio, 'resultados_acumulados': resultados_acumulados,
        'es_utilidad': resultados_acumulados >= 0,
        'total_patrimonio_con_resultados': total_patrimonio_con_resultados,
        'total_pasivo_patrimonio': total_pasivo_patrimonio, 'esta_balanceado': esta_balanceado,
        'ecuacion_resumen': ecuacion_resumen, 'ec_total_debe': ec_total_debe,
        'ec_total_haber': ec_total_haber, 'ec_total_deudor': ec_total_deudor,
        'ec_total_acreedor': ec_total_acreedor,
    }
    return render(request, 'balance_general.html', context)


# ─── REPORTE COMPLETO EN PDF ───────────────────────────────────────────────────

import gc # Recolector de basura
from django.utils import timezone

def reporte_completo(request):
    if request.method == 'POST':
        empresa = request.POST.get('empresa', 'Mi Empresa').strip() or 'Mi Empresa'

        # Liberamos RAM antes de empezar
        gc.collect()

        context = get_reporte_context()
        context['empresa'] = empresa
        
        # --- LOGO EN BASE64 ---
        import base64
        try:
            logo_path = os.path.join(settings.BASE_DIR, 'UNILOGO.png')
            with open(logo_path, "rb") as image_file:
                encoded_string = base64.b64encode(image_file.read()).decode('utf-8')
                context['logo_base64'] = f"data:image/png;base64,{encoded_string}"
        except Exception:
            context['logo_base64'] = ""

        html = render_to_string('reporte_pdf.html', context)
        del context
        
        pdf_file = BytesIO()
        pisa_status = pisa.CreatePDF(BytesIO(html.encode('UTF-8')), dest=pdf_file)
        del html
        gc.collect()

        if pisa_status.err:
            messages.error(request, 'Error al generar el archivo PDF.')
            return redirect('reporte_completo')

        # Descarga directa del PDF en el navegador
        pdf_data = pdf_file.getvalue()
        pdf_file.close()

        nombre_archivo = f"Reporte_Contable_{empresa.replace(' ', '_')}.pdf"
        response = HttpResponse(pdf_data, content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="{nombre_archivo}"'
        return response

    return render(request, 'menu_reporte.html')

def eliminar_asiento(request, asiento_id):
    """
    Elimina un asiento contable específico y todos sus movimientos asociados.
    """
    asiento = get_object_or_404(AsientoContable, id=asiento_id)
    
    # Guardamos el ID para el mensaje de éxito antes de borrarlo
    asiento_num = asiento.id 
    
    # Al eliminar el asiento, los movimientos se borran en cascada 
    # por el models.CASCADE que tienes en tu modelo
    asiento.delete()
    
    messages.success(request, f'El Asiento #{asiento_num} fue eliminado correctamente.')
    return redirect('libro_diario')


# --- AÑADIR AL FINAL DE core/views.py ---

def editar_asiento(request, asiento_id):
    asiento = get_object_or_404(AsientoContable, id=asiento_id)
    if request.method == 'POST':
        movimientos_data, errors = validar_asiento_formulario(request.POST)
        if errors:
            for error in errors:
                messages.error(request, error)
            return redirect('libro_diario')

        with transaction.atomic():
            asiento.fecha = request.POST.get('fecha', '').strip()
            asiento.descripcion = request.POST.get('descripcion', '').strip()
            asiento.save()
            asiento.movimientos.all().delete()
            for movimiento in movimientos_data:
                Movimiento.objects.create(asiento=asiento, **movimiento)

        # --- MENSAJE CON HORA REAL ---
        ahora = timezone.localtime(timezone.now()).strftime("%d/%m/%Y a las %H:%M")
        messages.success(request, f"Asiento actualizado exitosamente el {ahora}.")
    return redirect('libro_diario')
# ─── CHATBOT DE ASISTENCIA FINANCIERA (GROQ AI) ──────────────────────────

def chatbot_api(request):
    """Propone asientos validados sin guardar, conservando el texto del chat."""
    if request.method != 'POST':
        return JsonResponse({'error': 'Método no permitido'}, status=405)

    if request.content_type == 'application/json':
        try:
            datos = json.loads(request.body)
        except (ValueError, UnicodeDecodeError):
            return JsonResponse({'error': 'JSON de solicitud no válido'}, status=400)
        if not isinstance(datos, dict):
            return JsonResponse({'error': 'JSON de solicitud no válido'}, status=400)
        mensaje = datos.get('message', '')
    else:
        mensaje = request.POST.get('message', '')
    if not isinstance(mensaje, str) or not mensaje.strip():
        return JsonResponse({'error': 'Mensaje vacío o no válido'}, status=400)

    try:
        mensaje = mensaje.strip()
        pendiente = obtener_pendiente(request.session)
        if mensaje.lower().strip('.!') in {'cancelar', 'cancela', 'cancelar aclaración', 'cancelar aclaracion'}:
            request.session.pop(CLAVE_ACLARACION, None)
            return JsonResponse({'estado': 'cancelado', 'response': 'Aclaración cancelada.', 'status': 'success'})
        cuentas = list(CuentaContable.objects.all())
        if pendiente and consulta_opciones(mensaje):
            resultado = informar_opciones(mensaje, pendiente, cuentas)
            campo = pendiente.get('campo_pendiente', pendiente['datos_faltantes'][0])
            if any(p in campo for p in ('cuenta', 'tipo_gasto', 'contrapartida')):
                pendiente = {**pendiente, 'opciones_validas': [
                    o if 'id' in o else
                    {'id': o['cuenta_codigo'], 'etiqueta': o['cuenta_nombre'], 'valor': o}
                    for o in resultado['opciones']]}
                pendiente['opciones'] = pendiente['opciones_validas']
            request.session[CLAVE_ACLARACION] = {**pendiente, 'actualizada_en': time.time()}
            return JsonResponse({**resultado, 'status': 'success'})
        if pendiente and nuevo_hecho_completo(mensaje, cuentas):
            request.session.pop(CLAVE_ACLARACION, None)
            pendiente = None
        original = pendiente['mensaje_original'] if pendiente else mensaje
        if pendiente:
            hecho, detectados, seguimiento, _ = resolver_respuesta(mensaje, pendiente, cuentas)
            resultado = seguimiento.get('aclaracion_resolver') or generar_propuesta(
                hecho, datos_previos=detectados, seguimiento=seguimiento)
        else:
            resultado = generar_propuesta(mensaje)
        if resultado['estado'] == 'requiere_aclaracion':
            guardar_pendiente(request.session, original, resultado, pendiente, mensaje)
        if resultado['estado'] == 'propuesta':
            revision = preparar_revision(resultado)
            request.session.pop(CLAVE_ACLARACION, None)
            propuestas = _propuestas_vigentes(request)
            # Acotar datos temporales de la sesión; no almacenar conversaciones.
            propuestas = dict(list(propuestas.items())[-4:])
            identificador = uuid.uuid4().hex
            propuestas[identificador] = {'resultado': resultado, 'creada_en': time.time()}
            request.session[PROPUESTAS_SESION] = propuestas
            resultado = {
                **resultado, 'vista_previa': revision, 'propuesta_id': identificador,
                'revision_url': reverse('registrar_asiento') + '?propuesta=' + identificador,
            }

    except ErrorChatbot as exc:
        error = {'status': 'error', 'error': str(exc)}
        if exc.errores:
            error['errores'] = exc.errores
            error['error'] += ' ' + ' '.join(exc.errores)
        return JsonResponse(error, status=exc.status)
    return JsonResponse({**resultado, 'response': texto_respuesta(resultado), 'status': 'success'})


# ─── EXPORTACIÓN A EXCEL Y CSV ────────────────────────────────────────────────

def exportar_reporte(request, reporte, formato):
    """
    Controlador para exportar reportes a Excel (.xlsx) o CSV.
    reporte: 'completo', 'diario', 'balance-comprobacion', 'estado-resultados', 'balance-general'
    formato: 'excel', 'csv'
    """
    from . import export_utils
    from openpyxl import Workbook
    import io

    formato = formato.lower()
    reporte = reporte.lower()

    if formato == 'excel':
        wb = Workbook()
        if reporte == 'completo':
            content = export_utils.generar_excel_completo()
            filename = "Reporte_Contable_Completo.xlsx"
        elif reporte == 'diario':
            export_utils.build_excel_diario(wb, title_sheet="Libro Diario")
            buf = io.BytesIO()
            wb.save(buf)
            content = buf.getvalue()
            filename = "Libro_Diario.xlsx"
        elif reporte == 'balance-comprobacion':
            export_utils.build_excel_balance_comprobacion(wb, title_sheet="Balance Comprobación")
            if "Sheet" in wb.sheetnames and len(wb.sheetnames) > 1:
                del wb["Sheet"]
            buf = io.BytesIO()
            wb.save(buf)
            content = buf.getvalue()
            filename = "Balance_de_Comprobacion.xlsx"
        elif reporte == 'estado-resultados':
            export_utils.build_excel_estado_resultados(wb, title_sheet="Estado de Resultados")
            if "Sheet" in wb.sheetnames:
                del wb["Sheet"]
            buf = io.BytesIO()
            wb.save(buf)
            content = buf.getvalue()
            filename = "Estado_de_Resultados.xlsx"
        elif reporte == 'balance-general':
            export_utils.build_excel_balance_general(wb, title_sheet="Balance General")
            if "Sheet" in wb.sheetnames:
                del wb["Sheet"]
            buf = io.BytesIO()
            wb.save(buf)
            content = buf.getvalue()
            filename = "Balance_General.xlsx"
        else:
            return HttpResponse("Tipo de reporte no válido.", status=400)

        response = HttpResponse(
            content,
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    elif formato == 'csv':
        if reporte == 'diario':
            content = export_utils.generar_csv_diario()
            filename = "Libro_Diario.csv"
        elif reporte == 'balance-comprobacion':
            content = export_utils.generar_csv_balance_comprobacion()
            filename = "Balance_de_Comprobacion.csv"
        elif reporte == 'estado-resultados':
            content = export_utils.generar_csv_estado_resultados()
            filename = "Estado_de_Resultados.csv"
        elif reporte == 'balance-general':
            content = export_utils.generar_csv_balance_general()
            filename = "Balance_General.csv"
        else:
            return HttpResponse("Reporte CSV no disponible para esta opción.", status=400)

        response = HttpResponse(content, content_type='text/csv; charset=utf-8-sig')
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    return HttpResponse("Formato no soportado.", status=400)


