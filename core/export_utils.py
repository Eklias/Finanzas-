"""
Utilidades para exportación de reportes a Excel (.xlsx) y CSV.
Desarrollado para el Sistema Contable ContaSys - FIIS UNI.
"""
import csv
import io
from decimal import Decimal
from django.http import HttpResponse
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

from .models import AsientoContable, CuentaContable, Movimiento
from .reporte_utils import get_reporte_context


# ─── ESTILOS PARA EXCEL ───────────────────────────────────────────────────────

HEADER_FILL = PatternFill(start_color="1F3C88", end_color="1F3C88", fill_type="solid")
SUBHEADER_FILL = PatternFill(start_color="2980B9", end_color="2980B9", fill_type="solid")
TOTAL_FILL = PatternFill(start_color="EBF3FB", end_color="EBF3FB", fill_type="solid")
ACCENT_FILL = PatternFill(start_color="F2F4F8", end_color="F2F4F8", fill_type="solid")

FONT_TITLE = Font(name="Calibri", size=14, bold=True, color="1F3C88")
FONT_SUBTITLE = Font(name="Calibri", size=10, italic=True, color="555555")
FONT_HEADER = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
FONT_BOLD = Font(name="Calibri", size=11, bold=True)
FONT_NORMAL = Font(name="Calibri", size=11)

ALIGN_CENTER = Alignment(horizontal="center", vertical="center")
ALIGN_LEFT = Alignment(horizontal="left", vertical="center")
ALIGN_RIGHT = Alignment(horizontal="right", vertical="center")

BORDER_THIN = Side(border_style="thin", color="CCCCCC")
BORDER_DOUBLE = Side(border_style="double", color="333333")
CELL_BORDER = Border(left=BORDER_THIN, right=BORDER_THIN, top=BORDER_THIN, bottom=BORDER_THIN)
TOTAL_BORDER = Border(top=BORDER_THIN, bottom=BORDER_DOUBLE)

FORMAT_CURRENCY = '"S/" #,##0.00'


def _ajustar_anchos(ws):
    """Autoajusta el ancho de las columnas con un margen de holgura."""
    for col in ws.columns:
        max_len = 0
        col_letter = get_column_letter(col[0].column)
        for cell in col:
            val = str(cell.value or '')
            if len(val) > max_len:
                max_len = len(val)
        ws.column_dimensions[col_letter].width = max(max_len + 4, 12)


# ─── 1. EXCEL: LIBRO DIARIO ───────────────────────────────────────────────────

def build_excel_diario(wb, title_sheet="Libro Diario"):
    ws = wb.active if "Sheet" in wb.sheetnames else wb.create_sheet(title=title_sheet)
    ws.title = title_sheet

    ws.append(["SISTEMA CONTABLE CONTASYS - LIBRO DIARIO"])
    ws.append(["Registro cronológico de operaciones contables"])
    ws.append([])

    ws.cell(1, 1).font = FONT_TITLE
    ws.cell(2, 1).font = FONT_SUBTITLE

    headers = ["N° Asiento", "Fecha", "Glosa / Descripción", "Código", "Cuenta Contable", "Debe (S/)", "Haber (S/)"]
    ws.append(headers)
    header_row = 4

    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=header_row, column=col_idx)
        cell.fill = HEADER_FILL
        cell.font = FONT_HEADER
        cell.alignment = ALIGN_CENTER if col_idx in (1, 2, 4) else (ALIGN_RIGHT if col_idx in (6, 7) else ALIGN_LEFT)

    asientos = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id')
    current_row = 5
    total_debe = Decimal('0')
    total_haber = Decimal('0')

    for num, asiento in enumerate(asientos, 1):
        for mov in asiento.movimientos.all():
            monto_debe = float(mov.monto) if mov.tipo == 'debe' else 0.0
            monto_haber = float(mov.monto) if mov.tipo == 'haber' else 0.0
            
            if mov.tipo == 'debe':
                total_debe += mov.monto
            else:
                total_haber += mov.monto

            ws.append([
                num,
                asiento.fecha.strftime("%d/%m/%Y"),
                asiento.descripcion,
                mov.cuenta.codigo,
                mov.cuenta.nombre,
                monto_debe,
                monto_haber
            ])

            for c in range(1, 8):
                cell = ws.cell(row=current_row, column=c)
                cell.font = FONT_NORMAL
                cell.border = CELL_BORDER
                if c in (1, 2, 4):
                    cell.alignment = ALIGN_CENTER
                elif c in (6, 7):
                    cell.alignment = ALIGN_RIGHT
                    cell.number_format = FORMAT_CURRENCY
                else:
                    cell.alignment = ALIGN_LEFT

            current_row += 1

    # Fila de totales
    ws.append(["", "", "", "", "TOTAL GENERAL", float(total_debe), float(total_haber)])
    for c in range(1, 8):
        cell = ws.cell(row=current_row, column=c)
        cell.font = FONT_BOLD
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER
        if c in (6, 7):
            cell.alignment = ALIGN_RIGHT
            cell.number_format = FORMAT_CURRENCY
        elif c == 5:
            cell.alignment = ALIGN_RIGHT

    _ajustar_anchos(ws)
    return ws


# ─── 2. EXCEL: BALANCE DE COMPROBACIÓN ────────────────────────────────────────

def build_excel_balance_comprobacion(wb, title_sheet="Balance Comprobación"):
    ws = wb.create_sheet(title=title_sheet) if title_sheet in wb.sheetnames or wb.active.title != "Sheet" else wb.active
    if ws.title != title_sheet:
        ws = wb.create_sheet(title=title_sheet)

    ws.append(["SISTEMA CONTABLE CONTASYS - BALANCE DE COMPROBACIÓN"])
    ws.append(["Sumas del Mayor y Saldos de Cuentas"])
    ws.append([])

    ws.cell(1, 1).font = FONT_TITLE
    ws.cell(2, 1).font = FONT_SUBTITLE

    # Encabezados en 2 niveles
    ws.append(["Código", "Cuenta Contable", "SUMAS DEL MAYOR", "", "SALDOS", ""])
    ws.append(["", "", "Debe (S/)", "Haber (S/)", "Deudor (S/)", "Acreedor (S/)"])
    
    ws.merge_cells("A4:A5")
    ws.merge_cells("B4:B5")
    ws.merge_cells("C4:D4")
    ws.merge_cells("E4:F4")

    for r in range(4, 6):
        for c in range(1, 7):
            cell = ws.cell(row=r, column=c)
            cell.fill = HEADER_FILL
            cell.font = FONT_HEADER
            cell.alignment = ALIGN_CENTER
            cell.border = CELL_BORDER

    ctx = get_reporte_context()
    datos = ctx.get('bal_comp_datos', [])
    current_row = 6

    for item in datos:
        c = item['cuenta']
        ws.append([
            c.codigo,
            c.nombre,
            float(item['total_debe']),
            float(item['total_haber']),
            float(item['saldo_deudor']),
            float(item['saldo_acreedor']),
        ])
        for col_idx in range(1, 7):
            cell = ws.cell(row=current_row, column=col_idx)
            cell.font = FONT_NORMAL
            cell.border = CELL_BORDER
            if col_idx == 1:
                cell.alignment = ALIGN_CENTER
            elif col_idx == 2:
                cell.alignment = ALIGN_LEFT
            else:
                cell.alignment = ALIGN_RIGHT
                cell.number_format = FORMAT_CURRENCY
        current_row += 1

    # Fila de Totales
    ws.append([
        "TOTAL",
        "SUMAS Y SALDOS CUADRADOS",
        float(ctx.get('gran_total_debe', 0)),
        float(ctx.get('gran_total_haber', 0)),
        float(ctx.get('gran_saldo_deudor', 0)),
        float(ctx.get('gran_saldo_acreedor', 0)),
    ])
    for col_idx in range(1, 7):
        cell = ws.cell(row=current_row, column=col_idx)
        cell.font = FONT_BOLD
        cell.fill = TOTAL_FILL
        cell.border = TOTAL_BORDER
        if col_idx in (1, 2):
            cell.alignment = ALIGN_LEFT if col_idx == 2 else ALIGN_CENTER
        else:
            cell.alignment = ALIGN_RIGHT
            cell.number_format = FORMAT_CURRENCY

    _ajustar_anchos(ws)
    return ws


# ─── 3. EXCEL: ESTADO DE RESULTADOS ───────────────────────────────────────────

def build_excel_estado_resultados(wb, title_sheet="Estado de Resultados"):
    ws = wb.create_sheet(title=title_sheet)
    ws.append(["SISTEMA CONTABLE CONTASYS - ESTADO DE RESULTADOS"])
    ws.append(["Estado Financiero de Rendimiento Económico"])
    ws.append([])

    ws.cell(1, 1).font = FONT_TITLE
    ws.cell(2, 1).font = FONT_SUBTITLE

    ws.append(["CONCEPTO", "IMPORTE (S/)"])
    ws.cell(4, 1).fill = HEADER_FILL
    ws.cell(4, 1).font = FONT_HEADER
    ws.cell(4, 2).fill = HEADER_FILL
    ws.cell(4, 2).font = FONT_HEADER
    ws.cell(4, 2).alignment = ALIGN_RIGHT

    ctx = get_reporte_context()
    lineas = [
        ("Ventas Netas (Ingresos Operacionales)", float(ctx.get('er_total_ventas', 0)), False),
        ("(-) Costo de Ventas", -float(ctx.get('er_total_costo_ventas', 0)), False),
        ("(=) UTILIDAD BRUTA", float(ctx.get('er_utilidad_bruta', 0)), True),
        ("(-) Gastos Operativos (Adm. y Ventas)", -float(ctx.get('er_total_gastos_operativos', 0)), False),
        ("(=) UTILIDAD OPERATIVA", float(ctx.get('er_utilidad_operativa', 0)), True),
        ("(-) Gastos Financieros", -float(ctx.get('er_total_gastos_financieros', 0)), False),
        ("(+) Otros Ingresos", float(ctx.get('er_total_otros_ingresos', 0)), False),
        ("(-) Otros Gastos", -float(ctx.get('er_total_otros_gastos', 0)), False),
        ("(=) RESULTADO ANTES DE IMPUESTOS", float(ctx.get('er_utilidad_antes_impuesto', 0)), True),
        ("(-) Impuesto a la Renta Estimado (30%)", -float(ctx.get('er_impuesto', 0)), False),
        ("(=) UTILIDAD NETA DEL EJERCICIO", float(ctx.get('er_utilidad_neta', 0)), True),
    ]

    r = 5
    for concepto, monto, es_total in lineas:
        ws.append([concepto, monto])
        c1 = ws.cell(row=r, column=1)
        c2 = ws.cell(row=r, column=2)
        c2.number_format = FORMAT_CURRENCY
        c2.alignment = ALIGN_RIGHT

        if es_total:
            c1.font = FONT_BOLD
            c2.font = FONT_BOLD
            c1.fill = TOTAL_FILL
            c2.fill = TOTAL_FILL
            c1.border = TOTAL_BORDER
            c2.border = TOTAL_BORDER
        else:
            c1.font = FONT_NORMAL
            c2.font = FONT_NORMAL
            c1.border = CELL_BORDER
            c2.border = CELL_BORDER
        r += 1

    _ajustar_anchos(ws)
    return ws


# ─── 4. EXCEL: BALANCE GENERAL ────────────────────────────────────────────────

def build_excel_balance_general(wb, title_sheet="Balance General"):
    ws = wb.create_sheet(title=title_sheet)
    ws.append(["SISTEMA CONTABLE CONTASYS - BALANCE GENERAL"])
    ws.append(["Estado de Situación Financiera"])
    ws.append([])

    ws.cell(1, 1).font = FONT_TITLE
    ws.cell(2, 1).font = FONT_SUBTITLE

    ws.append(["CATEGORÍA", "CÓDIGO", "CUENTA CONTABLE", "SALDO (S/)"])
    for c in range(1, 5):
        cell = ws.cell(row=4, column=c)
        cell.fill = HEADER_FILL
        cell.font = FONT_HEADER
        cell.alignment = ALIGN_CENTER if c in (1, 2) else (ALIGN_RIGHT if c == 4 else ALIGN_LEFT)

    ctx = get_reporte_context()
    current_row = 5

    def escribir_seccion(titulo, items, total_seccion):
        nonlocal current_row
        for it in items:
            ws.append([titulo, it['cuenta'].codigo, it['cuenta'].nombre, float(it['saldo'])])
            for c in range(1, 5):
                cell = ws.cell(row=current_row, column=c)
                cell.font = FONT_NORMAL
                cell.border = CELL_BORDER
                if c == 4:
                    cell.alignment = ALIGN_RIGHT
                    cell.number_format = FORMAT_CURRENCY
            current_row += 1
        
        # Subtotal
        ws.append(["", "", f"TOTAL {titulo.upper()}", float(total_seccion)])
        for c in range(1, 5):
            cell = ws.cell(row=current_row, column=c)
            cell.font = FONT_BOLD
            cell.fill = TOTAL_FILL
            cell.border = TOTAL_BORDER
            if c == 4:
                cell.alignment = ALIGN_RIGHT
                cell.number_format = FORMAT_CURRENCY
        current_row += 1

    escribir_seccion("Activo", ctx.get('bg_activos', []), ctx.get('bg_total_activos', 0))
    escribir_seccion("Pasivo", ctx.get('bg_pasivos', []), ctx.get('bg_total_pasivos', 0))
    escribir_seccion("Patrimonio", ctx.get('bg_patrimonio', []), ctx.get('bg_total_patrimonio', 0))

    # Total Pasivo + Patrimonio
    ws.append(["", "", "TOTAL PASIVO + PATRIMONIO", float(ctx.get('bg_total_pasivos', 0) + ctx.get('bg_total_patrimonio', 0))])
    for c in range(1, 5):
        cell = ws.cell(row=current_row, column=c)
        cell.font = Font(name="Calibri", size=11, bold=True, color="1F3C88")
        cell.fill = PatternFill(start_color="D6E4F0", end_color="D6E4F0", fill_type="solid")
        cell.border = TOTAL_BORDER
        if c == 4:
            cell.alignment = ALIGN_RIGHT
            cell.number_format = FORMAT_CURRENCY

    _ajustar_anchos(ws)
    return ws


# ─── GENERADOR DE EXCEL COMPLETO (MULTI-HOJA) ─────────────────────────────────

def generar_excel_completo():
    wb = Workbook()
    # Eliminar hoja por defecto vacía o usarla
    build_excel_diario(wb, title_sheet="Libro Diario")
    build_excel_balance_comprobacion(wb, title_sheet="Balance de Comprobación")
    build_excel_estado_resultados(wb, title_sheet="Estado de Resultados")
    build_excel_balance_general(wb, title_sheet="Balance General")

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output.getvalue()


# ─── GENERADORES CSV INDIVIDUALES ─────────────────────────────────────────────

def generar_csv_diario():
    output = io.StringIO()
    # UTF-8 BOM para apertura perfecta en Excel en español
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Nro Asiento", "Fecha", "Descripcion / Glosa", "Codigo Cuenta", "Nombre Cuenta", "Debe", "Haber"])

    asientos = AsientoContable.objects.prefetch_related('movimientos__cuenta').order_by('fecha', 'id')
    for num, a in enumerate(asientos, 1):
        for m in a.movimientos.all():
            debe = f"{m.monto:.2f}" if m.tipo == 'debe' else "0.00"
            haber = f"{m.monto:.2f}" if m.tipo == 'haber' else "0.00"
            writer.writerow([num, a.fecha.strftime("%d/%m/%Y"), a.descripcion, m.cuenta.codigo, m.cuenta.nombre, debe, haber])

    return output.getvalue().encode('utf-8-sig')


def generar_csv_balance_comprobacion():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Codigo", "Cuenta Contable", "Total Debe", "Total Haber", "Saldo Deudor", "Saldo Acreedor"])

    ctx = get_reporte_context()
    for item in ctx.get('bal_comp_datos', []):
        c = item['cuenta']
        writer.writerow([
            c.codigo,
            c.nombre,
            f"{item['total_debe']:.2f}",
            f"{item['total_haber']:.2f}",
            f"{item['saldo_deudor']:.2f}",
            f"{item['saldo_acreedor']:.2f}"
        ])

    writer.writerow([
        "TOTALES",
        "CUADRE GENERAL",
        f"{ctx.get('gran_total_debe', 0):.2f}",
        f"{ctx.get('gran_total_haber', 0):.2f}",
        f"{ctx.get('gran_saldo_deudor', 0):.2f}",
        f"{ctx.get('gran_saldo_acreedor', 0):.2f}"
    ])
    return output.getvalue().encode('utf-8-sig')


def generar_csv_estado_resultados():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Concepto", "Monto (PEN)"])

    ctx = get_reporte_context()
    lineas = [
        ("Ventas Netas", f"{ctx.get('er_total_ventas', 0):.2f}"),
        ("(-) Costo de Ventas", f"-{ctx.get('er_total_costo_ventas', 0):.2f}"),
        ("(=) UTILIDAD BRUTA", f"{ctx.get('er_utilidad_bruta', 0):.2f}"),
        ("(-) Gastos Operativos", f"-{ctx.get('er_total_gastos_operativos', 0):.2f}"),
        ("(=) UTILIDAD OPERATIVA", f"{ctx.get('er_utilidad_operativa', 0):.2f}"),
        ("(-) Gastos Financieros", f"-{ctx.get('er_total_gastos_financieros', 0):.2f}"),
        ("(+) Otros Ingresos", f"{ctx.get('er_total_otros_ingresos', 0):.2f}"),
        ("(-) Otros Gastos", f"{-ctx.get('er_total_otros_gastos', 0):.2f}"),
        ("(=) RESULTADO ANTES DE IMPUESTO", f"{ctx.get('er_utilidad_antes_impuesto', 0):.2f}"),
        ("(-) Impuesto a la Renta (30%)", f"-{ctx.get('er_impuesto', 0):.2f}"),
        ("(=) UTILIDAD NETA DEL EJERCICIO", f"{ctx.get('er_utilidad_neta', 0):.2f}"),
    ]
    for c, m in lineas:
        writer.writerow([c, m])

    return output.getvalue().encode('utf-8-sig')


def generar_csv_balance_general():
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(["Categoria", "Codigo", "Cuenta", "Saldo (PEN)"])

    ctx = get_reporte_context()
    for item in ctx.get('bg_activos', []):
        writer.writerow(["Activo", item['cuenta'].codigo, item['cuenta'].nombre, f"{item['saldo']:.2f}"])
    writer.writerow(["Activo", "TOTAL", "TOTAL ACTIVOS", f"{ctx.get('bg_total_activos', 0):.2f}"])

    for item in ctx.get('bg_pasivos', []):
        writer.writerow(["Pasivo", item['cuenta'].codigo, item['cuenta'].nombre, f"{item['saldo']:.2f}"])
    writer.writerow(["Pasivo", "TOTAL", "TOTAL PASIVOS", f"{ctx.get('bg_total_pasivos', 0):.2f}"])

    for item in ctx.get('bg_patrimonio', []):
        writer.writerow(["Patrimonio", item['cuenta'].codigo, item['cuenta'].nombre, f"{item['saldo']:.2f}"])
    writer.writerow(["Patrimonio", "TOTAL", "TOTAL PATRIMONIO", f"{ctx.get('bg_total_patrimonio', 0):.2f}"])

    total_pp = ctx.get('bg_total_pasivos', 0) + ctx.get('bg_total_patrimonio', 0)
    writer.writerow(["Ecuacion", "TOTAL", "TOTAL PASIVO + PATRIMONIO", f"{total_pp:.2f}"])

    return output.getvalue().encode('utf-8-sig')
