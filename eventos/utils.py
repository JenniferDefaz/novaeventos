"""
utils.py — NovaEventos
Funciones auxiliares reutilizables:
  - generar_pdf_factura: genera el PDF de la cotización/factura con ReportLab
  - enviar_correo_aprobada_async: envía email al cliente cuando se aprueba, con PDF adjunto
  - enviar_correo_rechazada_async: envía email al cliente cuando se rechaza
Todas las funciones de correo se invocan en un hilo separado para no bloquear la respuesta.
"""
import io
import os
import threading

import qrcode
from PIL import Image as PilImage

from django.core.mail import EmailMessage

# ReportLab
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import cm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, HRFlowable, Image
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT


# ============================================================
# GENERACIÓN DE QR
# ============================================================

def _generar_qr_buffer(texto):
    """
    Genera un código QR con el texto dado y devuelve un BytesIO con la imagen PNG.
    """
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=6,
        border=2,
    )
    qr.add_data(texto)
    qr.make(fit=True)
    img = qr.make_image(fill_color='black', back_color='white')
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    buf.seek(0)
    return buf


# ============================================================
# GENERACIÓN DE PDF
# ============================================================

def generar_pdf_factura(evento):
    """
    Genera un PDF de factura/cotización formal para el evento dado.
    Devuelve un objeto BytesIO con el contenido del PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        leftMargin=2 * cm,
        rightMargin=2 * cm,
        topMargin=2 * cm,
        bottomMargin=2 * cm,
    )

    styles = getSampleStyleSheet()

    # ---- Estilos personalizados ----
    estilo_titulo = ParagraphStyle(
        'titulo',
        parent=styles['Title'],
        fontSize=22,
        textColor=colors.HexColor('#1a1a2e'),
        spaceAfter=4,
        alignment=TA_CENTER,
    )
    estilo_subtitulo = ParagraphStyle(
        'subtitulo',
        parent=styles['Normal'],
        fontSize=11,
        textColor=colors.HexColor('#555555'),
        alignment=TA_CENTER,
        spaceAfter=2,
    )
    estilo_seccion = ParagraphStyle(
        'seccion',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#0B3C5D'),
        fontName='Helvetica-Bold',
        spaceBefore=12,
        spaceAfter=4,
    )
    estilo_normal = ParagraphStyle(
        'normal',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#333333'),
        spaceAfter=3,
    )
    estilo_pie = ParagraphStyle(
        'pie',
        parent=styles['Normal'],
        fontSize=8,
        textColor=colors.HexColor('#888888'),
        alignment=TA_CENTER,
        spaceBefore=12,
    )

    cotizacion = evento.cotizacion_origen
    cliente = cotizacion.cliente
    salon = evento.salon

    elementos = []

    # ---- Encabezado ----
    elementos.append(Paragraph('NOVA<b>EVENTOS</b>', estilo_titulo))
    elementos.append(Paragraph('Gestión de Eventos, Banquetes y Centros de Convenciones', estilo_subtitulo))
    elementos.append(HRFlowable(width="100%", thickness=2, color=colors.HexColor('#D4AF37'), spaceAfter=8))

    # ---- Número de comprobante ----
    elementos.append(Paragraph(f'<b>COMPROBANTE DE RESERVA / FACTURA PROFORMA</b>', ParagraphStyle(
        'fact_num',
        parent=styles['Normal'],
        fontSize=12,
        textColor=colors.HexColor('#0B3C5D'),
        alignment=TA_CENTER,
        spaceBefore=4,
        spaceAfter=2,
    )))
    elementos.append(Paragraph(f'Nro. EVT-{evento.id:05d}', ParagraphStyle(
        'num',
        parent=styles['Normal'],
        fontSize=10,
        textColor=colors.HexColor('#666666'),
        alignment=TA_CENTER,
        spaceAfter=10,
    )))

    # ---- Datos del cliente ----
    elementos.append(Paragraph('DATOS DEL CLIENTE', estilo_seccion))
    datos_cliente = [
        ['Nombre:', f'{cliente.user.get_full_name()}'],
        ['Correo:', f'{cliente.user.email}'],
        ['Cédula:', f'{cliente.cedula or "—"}'],
        ['Teléfono:', f'{cliente.telefono or "—"}'],
    ]
    tabla_cliente = Table(datos_cliente, colWidths=[4 * cm, 12 * cm])
    tabla_cliente.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#0B3C5D')),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#333333')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
    ]))
    elementos.append(tabla_cliente)

    # ---- Detalle del evento ----
    elementos.append(Paragraph('DETALLE DEL EVENTO', estilo_seccion))
    datos_evento = [
        ['Salón:', salon.nombre],
        ['Capacidad del salón:', f'{salon.capacidad} personas'],
        ['Fecha del evento:', f'{evento.fecha_evento_inicio:%d/%m/%Y}'],
        ['Horario:', f'{evento.fecha_evento_inicio:%H:%M} — {evento.fecha_evento_fin:%H:%M}'],
        ['Montaje desde:', f'{evento.fecha_montaje_inicio:%d/%m/%Y %H:%M}'],
        ['Desmontaje hasta:', f'{evento.fecha_desmontaje_fin:%d/%m/%Y %H:%M}'],
        ['N.° de invitados:', f'{cotizacion.numero_invitados}'],
        ['Incluye catering:', 'Sí' if cotizacion.incluye_catering else 'No'],
        ['Incluye audiovisuales:', 'Sí' if cotizacion.incluye_audiovisuales else 'No'],
    ]
    tabla_evento = Table(datos_evento, colWidths=[5 * cm, 11 * cm])
    tabla_evento.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 10),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#0B3C5D')),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#333333')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 0), (-1, -1), [colors.HexColor('#f9f9f9'), colors.white]),
    ]))
    elementos.append(tabla_evento)

    # ---- Precio ----
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#D4AF37'), spaceAfter=6))

    datos_precio = [
        ['PRECIO BASE DEL SALÓN:', f'${salon.precio_base:,.2f}'],
        ['PRECIO FINAL ACORDADO:', f'${evento.precio_final:,.2f}'],
    ]
    tabla_precio = Table(datos_precio, colWidths=[11 * cm, 5 * cm])
    tabla_precio.setStyle(TableStyle([
        ('FONTNAME', (0, 0), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, -1), 11),
        ('TEXTCOLOR', (0, 0), (0, -1), colors.HexColor('#333333')),
        ('TEXTCOLOR', (1, 0), (1, -1), colors.HexColor('#0B3C5D')),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#e8f4f8')),
        ('BOX', (0, 1), (-1, 1), 1, colors.HexColor('#0B3C5D')),
    ]))
    elementos.append(tabla_precio)

    # ---- Estado ----
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(Paragraph(
        f'Estado del evento: <b><font color="#008000">CONFIRMADO ✓</font></b>',
        ParagraphStyle('estado', parent=styles['Normal'], fontSize=11, spaceAfter=6)
    ))

    # ---- Código QR ----
    texto_qr = (
        f"NovaEventos — Reserva Confirmada\n"
        f"Cliente: {cliente.user.get_full_name()}\n"
        f"Salón: {salon.nombre}\n"
        f"Fecha: {evento.fecha_evento_inicio:%d/%m/%Y}\n"
        f"Nro. EVT-{evento.id:05d}"
    )
    qr_buf = _generar_qr_buffer(texto_qr)
    qr_img = Image(qr_buf, width=3.5 * cm, height=3.5 * cm)

    tabla_qr = Table(
        [[qr_img, Paragraph(
            '<b>Escanea para verificar tu reserva</b><br/>'
            f'<font color="#555555" size="9">Cliente: {cliente.user.get_full_name()}<br/>'
            f'Salón: {salon.nombre}<br/>'
            f'Fecha: {evento.fecha_evento_inicio:%d/%m/%Y}</font>',
            ParagraphStyle('qr_texto', parent=styles['Normal'], fontSize=10, leading=14)
        )]],
        colWidths=[4 * cm, 12 * cm]
    )
    tabla_qr.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('TOPPADDING', (0, 0), (-1, -1), 8),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#D4AF37')),
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#fffdf5')),
    ]))
    elementos.append(Spacer(1, 0.4 * cm))
    elementos.append(tabla_qr)

    # ---- Pie de página ----
    elementos.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor('#dddddd'), spaceBefore=16, spaceAfter=6))
    elementos.append(Paragraph(
        'Este documento es un comprobante de reserva generado automáticamente por el sistema NovaEventos.<br/>'
        'Para consultas: contacto@novaeventos.ec | +593 99 123 4567',
        estilo_pie
    ))

    doc.build(elementos)
    buffer.seek(0)
    return buffer


# ============================================================
# ENVÍO DE CORREO — CORREO DE APROBACIÓN (con PDF adjunto)
# ============================================================

def _enviar_correo_aprobada(evento):
    """Función interna que se ejecuta en un hilo separado."""
    try:
        cliente = evento.cotizacion_origen.cliente
        email_destino = cliente.user.email
        nombre = cliente.user.get_full_name()

        asunto = f'✅ Tu evento en NovaEventos fue APROBADO — {evento.salon.nombre}'
        cuerpo = (
            f'Hola {nombre},\n\n'
            f'Nos complace confirmarte que tu solicitud de cotización ha sido APROBADA.\n\n'
            f'📍 Salón: {evento.salon.nombre}\n'
            f'📅 Fecha del evento: {evento.fecha_evento_inicio:%d/%m/%Y}\n'
            f'🕐 Horario: {evento.fecha_evento_inicio:%H:%M} — {evento.fecha_evento_fin:%H:%M}\n'
            f'👥 N.° de invitados: {evento.cotizacion_origen.numero_invitados}\n'
            f'🍽️ Catering incluido: {"Sí" if evento.cotizacion_origen.incluye_catering else "No"}\n'
            f'🎤 Audiovisuales incluidos: {"Sí" if evento.cotizacion_origen.incluye_audiovisuales else "No"}\n'
            f'💰 Precio final: ${evento.precio_final:,.2f}\n\n'
            f'Adjuntamos tu factura proforma. Pronto un coordinador se pondrá en contacto contigo.\n\n'
            f'¡Gracias por confiar en NovaEventos!\n\n'
            f'— El equipo de NovaEventos'
        )

        correo = EmailMessage(asunto, cuerpo, to=[email_destino])
        pdf_buffer = generar_pdf_factura(evento)
        correo.attach(
            filename=f'Factura_NovaEventos_EVT-{evento.id:05d}.pdf',
            content=pdf_buffer.read(),
            mimetype='application/pdf'
        )
        correo.send(fail_silently=False)
        print(f'✅ Correo de aprobación enviado a {email_destino}')

    except Exception as e:
        print(f'❌ Error enviando correo de aprobación: {e}')


def enviar_correo_aprobada_async(evento):
    """Dispara el envío de correo de aprobación en un hilo separado."""
    hilo = threading.Thread(target=_enviar_correo_aprobada, args=(evento,), daemon=True)
    hilo.start()


# ============================================================
# ENVÍO DE CORREO — CORREO DE RECHAZO
# ============================================================

def _enviar_correo_rechazada(cotizacion):
    """Función interna que se ejecuta en un hilo separado."""
    try:
        email_destino = cotizacion.cliente.user.email
        nombre = cotizacion.cliente.user.get_full_name()

        asunto = f'Tu solicitud de cotización en NovaEventos — Resultado'
        cuerpo = (
            f'Hola {nombre},\n\n'
            f'Hemos revisado tu solicitud de cotización para el salón '
            f'"{cotizacion.salon_solicitado.nombre}" el día '
            f'{cotizacion.fecha_evento_tentativa:%d/%m/%Y}.\n\n'
            f'Lamentamos informarte que en esta ocasión no fue posible confirmar tu evento.\n'
        )

        if cotizacion.comentario_admin:
            cuerpo += f'\nMotivo indicado por nuestro equipo:\n"{cotizacion.comentario_admin}"\n'

        cuerpo += (
            f'\nTe invitamos a revisar otras fechas o salones disponibles en nuestro catálogo.\n\n'
            f'Para cualquier consulta no dudes en contactarnos.\n\n'
            f'— El equipo de NovaEventos'
        )

        correo = EmailMessage(asunto, cuerpo, to=[email_destino])
        correo.send(fail_silently=False)
        print(f'✅ Correo de rechazo enviado a {email_destino}')
    except Exception as e:
        print(f'❌ Error enviando correo de rechazo: {e}')


def enviar_correo_rechazada_async(cotizacion):
    """Dispara el envío de correo de rechazo en un hilo separado."""
    hilo = threading.Thread(target=_enviar_correo_rechazada, args=(cotizacion,), daemon=True)
    hilo.start()
