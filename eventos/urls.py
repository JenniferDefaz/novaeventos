from django.urls import path  
#Importamos la logica de negocios de la app Nomina
#El views es un archivo que se encarga de gestionar la logica de negocios de la app Nomina 
#LO estamos llamando 
from . import views


urlpatterns = [
    path('', views.inicio, name='inicio'),
    path('salones/', views.catalogo_salones, name='catalogo_salones'),
    path('salones/<int:salon_id>/', views.detalle_salon, name='detalle_salon'),

    # Registro y login
    path('registro/', views.registro_cliente, name='registro_cliente'),
    path('login/', views.iniciar_sesion, name='iniciar_sesion'),
    path('logout/', views.cerrar_sesion, name='cerrar_sesion'),

    # Cliente
    path('cotizar/<int:salon_id>/', views.solicitar_cotizacion, name='solicitar_cotizacion'),
    path('misCotizaciones/', views.mis_cotizaciones, name='mis_cotizaciones'),
    path('miEvento/<int:cotizacion_id>/', views.mi_evento, name='mi_evento'),
    # Faltaba: descargar_factura ya existía en views.py pero nunca se conectó a ninguna URL
    path('descargarFactura/<int:evento_id>/', views.descargar_factura, name='descargar_factura'),

    # Administrador
    path('panelCotizaciones/', views.panel_cotizaciones, name='panel_cotizaciones'),
    path('revisarCotizacion/<int:cotizacion_id>/', views.revisar_cotizacion, name='revisar_cotizacion'),
    path('aprobarCotizacion/<int:cotizacion_id>/', views.aprobar_cotizacion, name='aprobar_cotizacion'),
    path('rechazarCotizacion/<int:cotizacion_id>/', views.rechazar_cotizacion, name='rechazar_cotizacion'),

    # CRUD Salones (admin)
    path('adminSalones/', views.listado_salones_admin, name='listado_salones_admin'),
    path('adminSalones/crear/', views.crear_salon, name='crear_salon'),
    path('adminSalones/editar/<int:salon_id>/', views.editar_salon, name='editar_salon'),

    path('adminSalones/eliminar/<int:salon_id>/', views.eliminar_salon, name='eliminar_salon'),

    # CRUD Catering (admin)
    path('adminCatering/', views.listado_catering_admin, name='listado_catering_admin'),
    path('adminCatering/crear/', views.crear_catering, name='crear_catering'),
    path('adminCatering/editar/<int:proveedor_id>/', views.editar_catering, name='editar_catering'),
    path('adminCatering/eliminar/<int:proveedor_id>/', views.eliminar_catering, name='eliminar_catering'),

    # CRUD Equipos (admin)
    path('adminEquipos/', views.listado_equipos_admin, name='listado_equipos_admin'),
    path('adminEquipos/crear/', views.crear_equipo, name='crear_equipo'),
    path('adminEquipos/editar/<int:equipo_id>/', views.editar_equipo, name='editar_equipo'),
    path('adminEquipos/eliminar/<int:equipo_id>/', views.eliminar_equipo, name='eliminar_equipo'),

    # Coordinador
    path('misEventos/', views.mis_eventos_asignados, name='mis_eventos_asignados'),
    path('misEventos/<int:evento_id>/', views.detalle_evento_coordinador, name='detalle_evento_coordinador'),
    path('miDashboardCoord/', views.dashboard_coordinador, name='dashboard_coordinador'),
    path('miReporteCoord/', views.reporte_pdf_coordinador, name='reporte_pdf_coordinador'),

    # Asignar coordinador (admin)
    path('asignarCoordinador/<int:evento_id>/', views.asignar_coordinador, name='asignar_coordinador'),

    path('calendario/', views.calendario_salones, name='calendario_salones'),
    path('calendario/json/', views.eventos_calendario_json, name='eventos_calendario_json'),
    path('calendario/disponibilidad/', views.disponibilidad_salon_json, name='disponibilidad_salon_json'),
    path('disposicion/<int:evento_id>/', views.disposicion_salon, name='disposicion_salon'),
    path('disposicion/<int:evento_id>/guardar/', views.guardar_disposicion, name='guardar_disposicion'),
    path('nuevaCotizacion/', views.crear_cotizacion_admin, name='crear_cotizacion_admin'),
    path('editarCotizacion/<int:cotizacion_id>/', views.editar_cotizacion_admin, name='editar_cotizacion_admin'),
    path('eliminarCotizacion/<int:cotizacion_id>/', views.eliminar_cotizacion, name='eliminar_cotizacion'),
    path('dashboard/', views.dashboard_admin, name='dashboard_admin'),
    path('reportePdf/', views.reporte_pdf, name='reporte_pdf'),

    # Cliente
    path('miDashboard/', views.dashboard_cliente, name='dashboard_cliente'),
    path('miReporte/', views.reporte_pdf_cliente, name='reporte_pdf_cliente'),
]