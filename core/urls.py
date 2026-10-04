"""
URLs de la app core.
Define todas las rutas del sistema contable.
"""
from django.urls import path
from . import views

urlpatterns = [
    # Página principal
    path('', views.index, name='index'),

    # Gestión de cuentas contables
    path('cuentas/', views.gestionar_cuentas, name='gestionar_cuentas'),
    path('cuentas/eliminar/<int:cuenta_id>/', views.eliminar_cuenta, name='eliminar_cuenta'),

    # Registro de asientos
    path('asientos/registrar/', views.registrar_asiento, name='registrar_asiento'),
    path('asientos/eliminar/<int:asiento_id>/', views.eliminar_asiento, name='eliminar_asiento'),
    path('asientos/editar/<int:asiento_id>/', views.editar_asiento, name='editar_asiento'),

    # Reportes
    path('reportes/libro-diario/', views.libro_diario, name='libro_diario'),
    path('reportes/libro-mayor/', views.libro_mayor, name='libro_mayor'),
    path('reportes/balance-comprobacion/', views.balance_comprobacion, name='balance_comprobacion'),
    path('reportes/estado-resultados/', views.estado_resultados, name='estado_resultados'),
    path('reportes/balance-general/', views.balance_general, name='balance_general'),
    path('reporte-completo/', views.reporte_completo, name='reporte_completo'),
    path('exportar/<str:reporte>/<str:formato>/', views.exportar_reporte, name='exportar_reporte'),
    path('chatbot/', views.chatbot_api, name='chatbot_api'),
    path('procesar_imagen_asiento/', views.procesar_imagen_asiento, name='procesar_imagen_asiento'),
    path('transcribir_audio/', views.transcribir_audio, name='transcribir_audio'),
    path('guardar_operaciones_lote/', views.guardar_operaciones_lote, name='guardar_operaciones_lote'),
    path('exportar_caso_ia_excel/', views.exportar_caso_ia_excel, name='exportar_caso_ia_excel'),
    path('limpiar_asientos_caso/', views.limpiar_asientos_caso, name='limpiar_asientos_caso'),
]