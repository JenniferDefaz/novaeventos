from django.shortcuts import render, get_object_or_404, redirect
from django.contrib import messages
from django.contrib.auth.models import User
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.core.exceptions import ValidationError
from django.http import JsonResponse, Http404, FileResponse
from django.views.decorators.http import require_POST
import json
import re
import threading
from django.core.mail import EmailMessage
from datetime import datetime, timedelta
from django.utils import timezone
from django.db.models.deletion import ProtectedError
from django.db.models import Sum, Count
from django.db.models.functions import ExtractQuarter, ExtractMonth, ExtractYear
from django.db import transaction


from .models import (
    Usuario, Salon, ProveedorCatering, EquipoAudiovisual,
    Cotizacion, CotizacionCatering, CotizacionEquipo,
    Evento, AsignacionCatering, AsignacionEquipo, DisposicionSalon
)
from .utils import generar_pdf_factura, enviar_correo_aprobada_async, enviar_correo_rechazada_async


# ======================================================
# Helpers de rol
# ======================================================

def requiere_rol(usuario_django, rol_esperado):
    """Devuelve True si el User logueado tiene el rol de Usuario esperado."""
    try:
        return usuario_django.usuario.rol == rol_esperado
    except Usuario.DoesNotExist:
        return False


def es_administrador(user):
    return user.is_authenticated and requiere_rol(user, Usuario.Rol.ADMINISTRADOR)


def es_coordinador(user):
    return user.is_authenticated and requiere_rol(user, Usuario.Rol.COORDINADOR)


# ======================================================
# Helpers de validación
# ======================================================

def _validar_cedula_ecuatoriana(cedula):
    """
    Valida el algoritmo de dígito verificador de la cédula ecuatoriana (módulo 10).
    Devuelve True/False.
    """
    if not cedula.isdigit() or len(cedula) != 10:
        return False
    provincia = int(cedula[:2])
    if provincia < 1 or provincia > 24:
        return False
    if int(cedula[2]) >= 6:
        return False
    coeficientes = [2, 1, 2, 1, 2, 1, 2, 1, 2]
    suma = 0
    for i in range(9):
        valor = int(cedula[i]) * coeficientes[i]
        if valor >= 10:
            valor -= 9
        suma += valor
    resultado = (10 - (suma % 10)) % 10
    return resultado == int(cedula[9])


def _es_telefono_valido(telefono):
    return bool(re.fullmatch(r'[0-9]{10}', telefono or ''))


def _es_decimal_positivo(valor_str):
    try:
        return float(valor_str) > 0
    except (TypeError, ValueError):
        return False


def _es_entero_positivo(valor_str):
    try:
        return int(valor_str) > 0
    except (TypeError, ValueError):
        return False


# ======================================================
# PÁGINAS PÚBLICAS
# ======================================================

def inicio(request):
    return render(request, 'inicio.html')


# ======================================================
# REGISTRO Y LOGIN
# ======================================================

def enviar_correo_bienvenida(nombre, email):
    try:
        from eventos.utils import _enviar_via_brevo
        asunto = '¡Bienvenido a NovaEventos!'
        cuerpo = (
            f'Hola {nombre},\n\n'
            f'¡Bienvenido a NovaEventos! Tu cuenta fue creada exitosamente.\n\n'
            f'Ya puedes explorar nuestro catálogo de salones y solicitar la '
            f'cotización para tu próximo evento.\n\n'
            f'Gracias por confiar en nosotros.\n\n'
            f'— El equipo de NovaEventos'
        )
        _enviar_via_brevo(
            destinatario_email=email,
            destinatario_nombre=nombre,
            asunto=asunto,
            cuerpo_texto=cuerpo,
        )
    except Exception as e:
        print(f'❌ Error enviando correo de bienvenida a {email}: {e}')


def registro_cliente(request):
    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        apellido = request.POST.get('apellido', '').strip()
        email = request.POST.get('email', '').strip()
        cedula = request.POST.get('cedula', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        password = request.POST.get('password', '')

        # Validaciones backend
        if not nombre or not apellido or not email or not cedula or not telefono or not password:
            return render(request, 'registro_cliente.html', {'error': 'Todos los campos son obligatorios.'})

        if not re.fullmatch(r'[A-Za-zÁÉÍÓÚáéíóúÑñ\s]+', nombre):
            return render(request, 'registro_cliente.html', {'error': 'El nombre solo debe contener letras.'})

        if not re.fullmatch(r'[A-Za-zÁÉÍÓÚáéíóúÑñ\s]+', apellido):
            return render(request, 'registro_cliente.html', {'error': 'El apellido solo debe contener letras.'})

        if not _validar_cedula_ecuatoriana(cedula):
            return render(request, 'registro_cliente.html', {'error': 'La cédula ingresada no es válida.'})

        if not _es_telefono_valido(telefono):
            return render(request, 'registro_cliente.html', {'error': 'El teléfono debe tener exactamente 10 dígitos.'})

        if len(password) < 6:
            return render(request, 'registro_cliente.html', {'error': 'La contraseña debe tener mínimo 6 caracteres.'})

        if User.objects.filter(username=email).exists():
            return render(request, 'registro_cliente.html', {'error': 'Ya existe una cuenta con ese correo.'})

        if Usuario.objects.filter(cedula=cedula).exists():
            return render(request, 'registro_cliente.html', {'error': 'Ya existe una cuenta registrada con esa cédula.'})

        user = User.objects.create_user(
            username=email, email=email, password=password,
            first_name=nombre, last_name=apellido
        )
        Usuario.objects.create(user=user, rol=Usuario.Rol.CLIENTE, cedula=cedula, telefono=telefono)

        hilo = threading.Thread(target=enviar_correo_bienvenida, args=(nombre, email), daemon=True)
        hilo.start()

        login(request, user)
        messages.success(request, f'¡Bienvenido, {nombre}! Tu cuenta fue creada exitosamente.')
        return redirect('catalogo_salones')

    return render(request, 'registro_cliente.html')


def iniciar_sesion(request):
    if request.user.is_authenticated:
        return _redirigir_segun_rol(request.user)

    if request.method == 'POST':
        usuario_input = request.POST.get('usuario', '').strip()
        clave = request.POST.get('clave', '')
        user = authenticate(request, username=usuario_input, password=clave)

        if user is not None:
            login(request, user)
            nombre = user.get_full_name() or user.username
            try:
                rol = user.usuario.get_rol_display()
            except Exception:
                rol = 'Usuario'
            messages.success(request, f'¡Bienvenido, {nombre}! Has iniciado sesión como {rol}.')
            return _redirigir_segun_rol(user)
        else:
            return render(request, 'login.html', {'error': 'Usuario o contraseña incorrectos.'})

    return render(request, 'login.html')


def _redirigir_segun_rol(user):
    try:
        usuario = user.usuario
    except Usuario.DoesNotExist:
        return redirect('catalogo_salones')

    if usuario.es_administrador:
        return redirect('panel_cotizaciones')
    elif usuario.es_coordinador:
        return redirect('mis_eventos_asignados')
    else:
        return redirect('mis_cotizaciones')


def cerrar_sesion(request):
    logout(request)
    return redirect('iniciar_sesion')


# ======================================================
# CATÁLOGO PÚBLICO DE SALONES
# ======================================================

def catalogo_salones(request):
    salones = Salon.objects.filter(activo=True)
    return render(request, 'catalogo_salones.html', {'salones': salones})


def detalle_salon(request, salon_id):
    salon = get_object_or_404(Salon, id=salon_id, activo=True)
    return render(request, 'detalle_salon.html', {'salon': salon})


# ======================================================
# CLIENTE: solicitar y ver cotizaciones
# ======================================================

@login_required(login_url='iniciar_sesion')
def solicitar_cotizacion(request, salon_id):
    if not requiere_rol(request.user, Usuario.Rol.CLIENTE):
        messages.error(request, 'Solo los clientes pueden solicitar cotizaciones.')
        return redirect('catalogo_salones')

    salon = get_object_or_404(Salon, id=salon_id, activo=True)
    usuario = request.user.usuario
    proveedores = ProveedorCatering.objects.filter(activo=True)
    equipos = EquipoAudiovisual.objects.filter(activo=True)

    if request.method == 'POST':
        fecha = request.POST.get('fecha_evento_tentativa')
        hora_inicio = request.POST.get('hora_inicio_tentativa')
        hora_fin = request.POST.get('hora_fin_tentativa')
        invitados = request.POST.get('numero_invitados')
        proveedores_ids = request.POST.getlist('proveedores_catering')
        equipos_ids = request.POST.getlist('equipos')

        if not invitados or not invitados.isdigit() or int(invitados) < 1:
            messages.error(request, 'El número de invitados no es válido.')
            return render(request, 'solicitar_cotizacion.html', {
                'salon': salon, 'proveedores': proveedores, 'equipos': equipos
            })

        with transaction.atomic():
            cotizacion = Cotizacion.objects.create(
                cliente=usuario,
                salon_solicitado=salon,
                fecha_evento_tentativa=fecha,
                hora_inicio_tentativa=hora_inicio,
                hora_fin_tentativa=hora_fin,
                numero_invitados=int(invitados),
                incluye_catering=bool(proveedores_ids),
                incluye_audiovisuales=bool(equipos_ids),
            )

            for proveedor_id in proveedores_ids:
                proveedor = get_object_or_404(ProveedorCatering, id=proveedor_id, activo=True)
                CotizacionCatering.objects.create(cotizacion=cotizacion, proveedor=proveedor)

            for equipo_id in equipos_ids:
                cantidad = request.POST.get(f'cantidad_{equipo_id}', 1)
                equipo = get_object_or_404(EquipoAudiovisual, id=equipo_id, activo=True)
                CotizacionEquipo.objects.create(
                    cotizacion=cotizacion,
                    equipo=equipo,
                    cantidad=int(cantidad) if str(cantidad).isdigit() else 1
                )

            cotizacion.precio_sugerido = cotizacion.calcular_precio_sugerido()
            cotizacion.save()

        messages.success(request, 'Tu solicitud de cotización fue enviada. Te contactaremos pronto.')
        return redirect('mis_cotizaciones')

    return render(request, 'solicitar_cotizacion.html', {
        'salon': salon, 'proveedores': proveedores, 'equipos': equipos
    })


@login_required(login_url='iniciar_sesion')
def mis_cotizaciones(request):
    if not requiere_rol(request.user, Usuario.Rol.CLIENTE):
        messages.error(request, 'Esta sección es solo para clientes.')
        return redirect('catalogo_salones')

    cotizaciones = Cotizacion.objects.filter(cliente=request.user.usuario).order_by('-fecha_solicitud')
    return render(request, 'mis_cotizaciones.html', {'cotizaciones': cotizaciones})


@login_required(login_url='iniciar_sesion')
def mi_evento(request, cotizacion_id):
    """El cliente ve el detalle de su evento ya confirmado."""
    cotizacion = get_object_or_404(
        Cotizacion, id=cotizacion_id, cliente=request.user.usuario, estado=Cotizacion.Estado.APROBADA
    )
    evento = getattr(cotizacion, 'evento', None)
    return render(request, 'mi_evento.html', {'cotizacion': cotizacion, 'evento': evento})


@login_required(login_url='iniciar_sesion')
def descargar_factura(request, evento_id):
    """El cliente descarga el PDF de la factura de su evento."""
    evento = get_object_or_404(
        Evento, id=evento_id, cotizacion_origen__cliente=request.user.usuario
    )
    if not requiere_rol(request.user, Usuario.Rol.CLIENTE):
        messages.error(request, 'No tienes permiso para acceder a este recurso.')
        return redirect('catalogo_salones')

    if evento.factura_pdf:
        return FileResponse(evento.factura_pdf.open('rb'), as_attachment=True,
                            filename=f'Factura_NovaEventos_EVT-{evento.id:05d}.pdf')

    # Si el PDF no existe aún, lo generamos al vuelo
    buffer = generar_pdf_factura(evento)
    from django.http import HttpResponse
    response = HttpResponse(buffer.read(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Factura_NovaEventos_EVT-{evento.id:05d}.pdf"'
    return response


# ======================================================
# ADMINISTRADOR: revisar y aprobar/rechazar cotizaciones
# ======================================================

@login_required(login_url='iniciar_sesion')
def panel_cotizaciones(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    cotizaciones = Cotizacion.objects.all().select_related(
        'cliente__user', 'salon_solicitado'
    ).order_by('estado', '-fecha_solicitud')
    return render(request, 'panel_cotizaciones.html', {'cotizaciones': cotizaciones})


@login_required(login_url='iniciar_sesion')
def revisar_cotizacion(request, cotizacion_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    cotizacion = get_object_or_404(Cotizacion, id=cotizacion_id)

    if request.method == 'POST':
        comentario = request.POST.get('comentario_admin', '').strip()

        # El precio se toma siempre del cálculo automático del sistema;
        # el administrador no puede modificarlo manualmente.
        cotizacion.precio_total_estimado = cotizacion.calcular_precio_sugerido()
        cotizacion.comentario_admin = comentario
        cotizacion.save()

        messages.success(request, 'Cotización guardada. Ahora puedes aprobar o rechazar.')
        return redirect('revisar_cotizacion', cotizacion_id=cotizacion.id)

    return render(request, 'revisar_cotizacion.html', {'cotizacion': cotizacion})


@login_required(login_url='iniciar_sesion')
def aprobar_cotizacion(request, cotizacion_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para realizar esta acción.')
        return redirect('catalogo_salones')

    cotizacion = get_object_or_404(Cotizacion, id=cotizacion_id)

    if cotizacion.estado != Cotizacion.Estado.PENDIENTE:
        messages.warning(request, 'Esta cotización ya fue revisada anteriormente.')
        return redirect('panel_cotizaciones')

    # Si aún no se guardó el precio, calcularlo automáticamente ahora
    if not cotizacion.precio_total_estimado:
        cotizacion.precio_total_estimado = cotizacion.calcular_precio_sugerido()
        cotizacion.save(update_fields=['precio_total_estimado'])

    # Construir fechas con margen de montaje (3h antes) y desmontaje (2h después)
    fecha_evento_inicio = timezone.datetime.combine(
        cotizacion.fecha_evento_tentativa, cotizacion.hora_inicio_tentativa
    )
    fecha_evento_fin = timezone.datetime.combine(
        cotizacion.fecha_evento_tentativa, cotizacion.hora_fin_tentativa
    )
    fecha_montaje_inicio = fecha_evento_inicio - timezone.timedelta(hours=3)
    fecha_desmontaje_fin = fecha_evento_fin + timezone.timedelta(hours=2)

    evento = Evento(
        cotizacion_origen=cotizacion,
        salon=cotizacion.salon_solicitado,
        fecha_montaje_inicio=timezone.make_aware(fecha_montaje_inicio),
        fecha_evento_inicio=timezone.make_aware(fecha_evento_inicio),
        fecha_evento_fin=timezone.make_aware(fecha_evento_fin),
        fecha_desmontaje_fin=timezone.make_aware(fecha_desmontaje_fin),
        precio_final=cotizacion.precio_total_estimado,
    )

    try:
        evento.full_clean()
        evento.save()
    except ValidationError as e:
        messages.error(request, f'No se pudo confirmar el evento: {e.messages[0]}')
        return redirect('revisar_cotizacion', cotizacion_id=cotizacion.id)

    cotizacion.estado = Cotizacion.Estado.APROBADA
    cotizacion.fecha_respuesta = timezone.now()
    cotizacion.save()

    # Generar y guardar el PDF de la factura
    try:
        pdf_buffer = generar_pdf_factura(evento)
        nombre_archivo = f'EVT-{evento.id:05d}.pdf'
        from django.core.files.base import ContentFile
        evento.factura_pdf.save(nombre_archivo, ContentFile(pdf_buffer.read()), save=True)
    except Exception as e:
        print(f'❌ Error generando PDF de factura: {e}')

    # Refrescar objeto evento para que tenga el factura_pdf actualizado
    evento.refresh_from_db()

    # Enviar correo de aprobación con PDF adjunto (hilo separado)
    enviar_correo_aprobada_async(evento)

    messages.success(request, '✅ Cotización aprobada y evento confirmado. Se enviará el comprobante al cliente.')
    return redirect('panel_cotizaciones')


@login_required(login_url='iniciar_sesion')
def rechazar_cotizacion(request, cotizacion_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para realizar esta acción.')
        return redirect('catalogo_salones')

    cotizacion = get_object_or_404(Cotizacion, id=cotizacion_id)

    if cotizacion.estado == Cotizacion.Estado.PENDIENTE:
        cotizacion.estado = Cotizacion.Estado.RECHAZADA
        cotizacion.fecha_respuesta = timezone.now()
        cotizacion.save()

        # Enviar correo de rechazo (hilo separado)
        enviar_correo_rechazada_async(cotizacion)
        messages.warning(request, 'Cotización rechazada. Se notificó al cliente.')
    else:
        messages.info(request, 'Esta cotización ya fue procesada anteriormente.')

    return redirect('panel_cotizaciones')


# ======================================================
# CRUD DE SALONES (solo Administrador)
# ======================================================

@login_required(login_url='iniciar_sesion')
def listado_salones_admin(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    salones = Salon.objects.all().order_by('nombre')
    return render(request, 'admin_salones.html', {'salones': salones})


@login_required(login_url='iniciar_sesion')
def crear_salon(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        capacidad_str = request.POST.get('capacidad', '').strip()
        precio_str = request.POST.get('precio_base', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        activo = bool(request.POST.get('activo'))
        imagen = request.FILES.get('imagen')

        errores = []
        if not nombre:
            errores.append('El nombre del salón es obligatorio.')
        elif Salon.objects.filter(nombre=nombre).exists():
            errores.append('Ya existe un salón con ese nombre.')

        if not _es_entero_positivo(capacidad_str):
            errores.append('La capacidad debe ser un número entero positivo.')

        if not _es_decimal_positivo(precio_str):
            errores.append('El precio base debe ser un número mayor a cero.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'form_salon.html', {'salon': None})

        salon = Salon.objects.create(
            nombre=nombre,
            capacidad=int(capacidad_str),
            precio_base=float(precio_str),
            descripcion=descripcion,
            activo=activo,
        )
        if imagen:
            salon.imagen = imagen
            salon.save()

        messages.success(request, f'Salón "{nombre}" registrado exitosamente.')
        return redirect('listado_salones_admin')

    return render(request, 'form_salon.html', {'salon': None})


@login_required(login_url='iniciar_sesion')
def editar_salon(request, salon_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    salon = get_object_or_404(Salon, id=salon_id)

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        capacidad_str = request.POST.get('capacidad', '').strip()
        precio_str = request.POST.get('precio_base', '').strip()
        descripcion = request.POST.get('descripcion', '').strip()
        activo = bool(request.POST.get('activo'))
        imagen = request.FILES.get('imagen')

        errores = []
        if not nombre:
            errores.append('El nombre del salón es obligatorio.')
        elif Salon.objects.filter(nombre=nombre).exclude(id=salon_id).exists():
            errores.append('Ya existe otro salón con ese nombre.')

        if not _es_entero_positivo(capacidad_str):
            errores.append('La capacidad debe ser un número entero positivo.')

        if not _es_decimal_positivo(precio_str):
            errores.append('El precio base debe ser un número mayor a cero.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'form_salon.html', {'salon': salon})

        salon.nombre = nombre
        salon.capacidad = int(capacidad_str)
        salon.precio_base = float(precio_str)
        salon.descripcion = descripcion
        salon.activo = activo
        if imagen:
            salon.imagen = imagen
        salon.save()

        messages.success(request, f'Salón "{nombre}" actualizado exitosamente.')
        return redirect('listado_salones_admin')

    return render(request, 'form_salon.html', {'salon': salon})


@login_required(login_url='iniciar_sesion')
def eliminar_salon(request, salon_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    salon = get_object_or_404(Salon, id=salon_id)
    nombre = salon.nombre

    try:
        salon.delete()
        messages.success(request, f'"{nombre}" fue eliminado permanentemente.')
    except ProtectedError:
        messages.error(
            request,
            f'No se puede eliminar "{nombre}" porque ya tiene cotizaciones o '
            f'eventos asociados (esto protege tu historial). Si quieres que deje '
            f'de aparecer en el catálogo, edítalo y desmarca "Disponible para '
            f'cotizaciones" en vez de eliminarlo.'
        )

    return redirect('listado_salones_admin')

# ======================================================
# CRUD DE PROVEEDORES DE CATERING (solo Administrador)
# ======================================================

@login_required(login_url='iniciar_sesion')
def listado_catering_admin(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    proveedores = ProveedorCatering.objects.all().order_by('nombre_empresa')
    return render(request, 'admin_catering.html', {'proveedores': proveedores})


@login_required(login_url='iniciar_sesion')
def crear_catering(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    if request.method == 'POST':
        nombre_empresa = request.POST.get('nombre_empresa', '').strip()
        contacto = request.POST.get('contacto', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        especialidad = request.POST.get('especialidad', '').strip()
        precio_str = request.POST.get('precio_por_persona', '').strip()
        activo = bool(request.POST.get('activo'))

        errores = []
        if not nombre_empresa:
            errores.append('El nombre de la empresa es obligatorio.')
        if not contacto:
            errores.append('El nombre del contacto es obligatorio.')
        if not _es_telefono_valido(telefono):
            errores.append('El teléfono debe tener exactamente 10 dígitos.')
        if not especialidad:
            errores.append('La especialidad es obligatoria.')
        if not _es_decimal_positivo(precio_str):
            errores.append('El precio por persona debe ser mayor a cero.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'form_catering.html', {'proveedor': None})

        ProveedorCatering.objects.create(
            nombre_empresa=nombre_empresa,
            contacto=contacto,
            telefono=telefono,
            especialidad=especialidad,
            precio_por_persona=float(precio_str),
            activo=activo,
        )
        messages.success(request, f'Proveedor "{nombre_empresa}" registrado exitosamente.')
        return redirect('listado_catering_admin')

    return render(request, 'form_catering.html', {'proveedor': None})


@login_required(login_url='iniciar_sesion')
def editar_catering(request, proveedor_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    proveedor = get_object_or_404(ProveedorCatering, id=proveedor_id)

    if request.method == 'POST':
        nombre_empresa = request.POST.get('nombre_empresa', '').strip()
        contacto = request.POST.get('contacto', '').strip()
        telefono = request.POST.get('telefono', '').strip()
        especialidad = request.POST.get('especialidad', '').strip()
        precio_str = request.POST.get('precio_por_persona', '').strip()
        activo = bool(request.POST.get('activo'))

        errores = []
        if not nombre_empresa:
            errores.append('El nombre de la empresa es obligatorio.')
        if not contacto:
            errores.append('El nombre del contacto es obligatorio.')
        if not _es_telefono_valido(telefono):
            errores.append('El teléfono debe tener exactamente 10 dígitos.')
        if not especialidad:
            errores.append('La especialidad es obligatoria.')
        if not _es_decimal_positivo(precio_str):
            errores.append('El precio por persona debe ser mayor a cero.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'form_catering.html', {'proveedor': proveedor})

        proveedor.nombre_empresa = nombre_empresa
        proveedor.contacto = contacto
        proveedor.telefono = telefono
        proveedor.especialidad = especialidad
        proveedor.precio_por_persona = float(precio_str)
        proveedor.activo = activo
        proveedor.save()

        messages.success(request, f'Proveedor "{nombre_empresa}" actualizado exitosamente.')
        return redirect('listado_catering_admin')

    return render(request, 'form_catering.html', {'proveedor': proveedor})


@login_required(login_url='iniciar_sesion')
def eliminar_catering(request, proveedor_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    proveedor = get_object_or_404(ProveedorCatering, id=proveedor_id)
    nombre = proveedor.nombre_empresa

    try:
        proveedor.delete()
        messages.success(request, f'"{nombre}" fue eliminado exitosamente.')
    except ProtectedError:
        messages.error(
            request,
            f'No se puede eliminar "{nombre}" porque ya está asignado a uno o más eventos.'
        )

    return redirect('listado_catering_admin')

# ======================================================
# CRUD DE EQUIPOS AUDIOVISUALES (solo Administrador)
# ======================================================

@login_required(login_url='iniciar_sesion')
def listado_equipos_admin(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    equipos = EquipoAudiovisual.objects.all().order_by('categoria', 'nombre')
    return render(request, 'admin_equipos.html', {'equipos': equipos})


@login_required(login_url='iniciar_sesion')
def crear_equipo(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    categorias = EquipoAudiovisual.Categoria.choices

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        categoria = request.POST.get('categoria', '')
        cantidad_total = request.POST.get('cantidad_total', '')
        precio_unitario = request.POST.get('precio_unitario', '')

        if not nombre or len(nombre) < 2:
            messages.error(request, 'El nombre del equipo no es válido.')
            return render(request, 'form_equipo.html', {'equipo': None, 'categorias': categorias})

        if categoria not in dict(categorias):
            messages.error(request, 'Selecciona una categoría válida.')
            return render(request, 'form_equipo.html', {'equipo': None, 'categorias': categorias})

        if not cantidad_total.isdigit() or int(cantidad_total) < 1 or int(cantidad_total) > 500:
            messages.error(request, 'La cantidad debe ser un número entero entre 1 y 500.')
            return render(request, 'form_equipo.html', {'equipo': None, 'categorias': categorias})

        try:
            precio = float(precio_unitario)
            if precio <= 0 or precio > 10000:
                raise ValueError
        except ValueError:
            messages.error(request, 'El precio debe ser un número mayor a cero.')
            return render(request, 'form_equipo.html', {'equipo': None, 'categorias': categorias})

        EquipoAudiovisual.objects.create(
            nombre=nombre,
            categoria=categoria,
            cantidad_total=int(cantidad_total),
            precio_unitario=precio,
            activo=bool(request.POST.get('activo')),
        )
        messages.success(request, 'Equipo registrado exitosamente.')
        return redirect('listado_equipos_admin')

    return render(request, 'form_equipo.html', {'equipo': None, 'categorias': categorias})


@login_required(login_url='iniciar_sesion')
def editar_equipo(request, equipo_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    equipo = get_object_or_404(EquipoAudiovisual, id=equipo_id)

    if request.method == 'POST':
        nombre = request.POST.get('nombre', '').strip()
        categoria = request.POST.get('categoria', '').strip()
        cantidad_str = request.POST.get('cantidad_total', '').strip()
        precio_str = request.POST.get('precio_unitario', '').strip()
        activo = bool(request.POST.get('activo'))

        categorias_validas = [c[0] for c in EquipoAudiovisual.Categoria.choices]
        errores = []

        if not nombre:
            errores.append('El nombre del equipo es obligatorio.')
        if categoria not in categorias_validas:
            errores.append('Debes seleccionar una categoría válida.')
        if not _es_entero_positivo(cantidad_str):
            errores.append('La cantidad total debe ser un entero mayor a cero.')
        if not _es_decimal_positivo(precio_str):
            errores.append('El precio unitario debe ser mayor a cero.')

        if errores:
            for e in errores:
                messages.error(request, e)
            return render(request, 'form_equipo.html', {
                'equipo': equipo, 'categorias': EquipoAudiovisual.Categoria.choices
            })

        equipo.nombre = nombre
        equipo.categoria = categoria
        equipo.cantidad_total = int(cantidad_str)
        equipo.precio_unitario = float(precio_str)
        equipo.activo = activo
        equipo.save()

        messages.success(request, f'Equipo "{nombre}" actualizado exitosamente.')
        return redirect('listado_equipos_admin')

    return render(request, 'form_equipo.html', {
        'equipo': equipo,
        'categorias': EquipoAudiovisual.Categoria.choices
    })


@login_required(login_url='iniciar_sesion')
def eliminar_equipo(request, equipo_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    equipo = get_object_or_404(EquipoAudiovisual, id=equipo_id)
    nombre = equipo.nombre

    try:
        equipo.delete()
        messages.success(request, f'"{nombre}" fue eliminado exitosamente.')
    except ProtectedError:
        messages.error(
            request,
            f'No se puede eliminar "{nombre}" porque ya está asignado a uno o más eventos. '
            f'Puedes desactivarlo en su lugar para que no se use en nuevos eventos.'
        )

    return redirect('listado_equipos_admin')
# ======================================================
# ADMINISTRADOR: asignar coordinador a un evento confirmado
# ======================================================

@login_required(login_url='iniciar_sesion')
def asignar_coordinador(request, evento_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    evento = get_object_or_404(Evento, id=evento_id)

    if request.method == 'POST':
        coordinador_id = request.POST.get('coordinador', '').strip()

        if not coordinador_id:
            messages.error(request, 'Debes seleccionar un coordinador.')
            coordinadores = Usuario.objects.filter(rol=Usuario.Rol.COORDINADOR)
            return render(request, 'asignar_coordinador.html', {'evento': evento, 'coordinadores': coordinadores})

        coordinador = get_object_or_404(Usuario, id=coordinador_id, rol=Usuario.Rol.COORDINADOR)
        evento.coordinador = coordinador
        evento.save()
        messages.success(request, f'Coordinador "{coordinador.user.get_full_name()}" asignado al evento exitosamente.')
        return redirect('panel_cotizaciones')

    coordinadores = Usuario.objects.filter(rol=Usuario.Rol.COORDINADOR)
    return render(request, 'asignar_coordinador.html', {'evento': evento, 'coordinadores': coordinadores})


# ======================================================
# COORDINADOR: eventos asignados a él
# ======================================================

@login_required(login_url='iniciar_sesion')
def mis_eventos_asignados(request):
    if not es_coordinador(request.user):
        messages.error(request, 'Esta sección es solo para coordinadores.')
        return redirect('catalogo_salones')

    eventos = Evento.objects.filter(coordinador=request.user.usuario).select_related(
        'salon', 'cotizacion_origen__cliente__user'
    ).order_by('fecha_evento_inicio')
    return render(request, 'mis_eventos_asignados.html', {'eventos': eventos})


@login_required(login_url='iniciar_sesion')
def detalle_evento_coordinador(request, evento_id):
    if not es_coordinador(request.user):
        messages.error(request, 'Esta sección es solo para coordinadores.')
        return redirect('catalogo_salones')

    evento = get_object_or_404(Evento, id=evento_id, coordinador=request.user.usuario)
    equipos_disponibles = EquipoAudiovisual.objects.filter(activo=True)
    asignaciones_catering = AsignacionCatering.objects.filter(evento=evento).select_related('proveedor')
    asignaciones_equipos = AsignacionEquipo.objects.filter(evento=evento).select_related('equipo')

    # IDs de proveedores ya asignados al evento (para excluirlos del selector)
    ids_ya_asignados = set(asignaciones_catering.values_list('proveedor_id', flat=True))
    # Solo muestra en el selector los que NO están ya asignados al evento
    proveedores_disponibles = ProveedorCatering.objects.filter(activo=True).exclude(id__in=ids_ya_asignados)
    # Proveedores que el cliente eligió al cotizar (referencia visual para el coordinador)
    catering_cotizacion = evento.cotizacion_origen.catering_seleccionado.select_related('proveedor')

    # Equipos que el cliente pidió en la cotización (referencia visual)
    equipos_cotizacion = evento.cotizacion_origen.equipos_seleccionados.select_related('equipo')

    # Manejo del cambio de estado
    if request.method == 'POST':
        accion = request.POST.get('accion', '')

        if accion == 'cambiar_estado':
            nuevo_estado = request.POST.get('nuevo_estado', '').strip()
            if not nuevo_estado:
                messages.error(request, 'Debes seleccionar un nuevo estado.')
            else:
                try:
                    evento.cambiar_estado(nuevo_estado)
                    messages.success(request, f'Estado del evento actualizado a "{evento.get_estado_display()}".')
                except ValidationError as e:
                    messages.error(request, str(e.message))

        elif accion == 'asignar_catering':
            proveedor_id = request.POST.get('proveedor_id', '').strip()
            tipo_servicio = request.POST.get('tipo_servicio', '').strip()
            if not proveedor_id or not tipo_servicio:
                messages.error(request, 'Selecciona un proveedor e indica el tipo de servicio.')
            else:
                proveedor = get_object_or_404(ProveedorCatering, id=proveedor_id, activo=True)
                _, creado = AsignacionCatering.objects.get_or_create(
                    evento=evento, proveedor=proveedor, tipo_servicio=tipo_servicio
                )
                if creado:
                    messages.success(request, f'Proveedor "{proveedor.nombre_empresa}" asignado.')
                else:
                    messages.info(request, 'Ese proveedor ya estaba asignado con ese tipo de servicio.')

        elif accion == 'eliminar_catering':
            asignacion_id = request.POST.get('asignacion_id', '').strip()
            AsignacionCatering.objects.filter(id=asignacion_id, evento=evento).delete()
            messages.warning(request, 'Proveedor de catering removido del evento.')

        elif accion == 'asignar_equipo':
            equipo_id = request.POST.get('equipo_id', '').strip()
            cantidad_str = request.POST.get('cantidad_asignada', '1').strip()
            if not equipo_id:
                messages.error(request, 'Debes seleccionar un equipo.')
            elif not _es_entero_positivo(cantidad_str):
                messages.error(request, 'La cantidad debe ser un entero mayor a cero.')
            else:
                equipo = get_object_or_404(EquipoAudiovisual, id=equipo_id, activo=True)
                asignacion, creada = AsignacionEquipo.objects.get_or_create(
                    evento=evento, equipo=equipo,
                    defaults={'cantidad_asignada': int(cantidad_str)}
                )
                if not creada:
                    asignacion.cantidad_asignada = int(cantidad_str)
                try:
                    asignacion.full_clean()
                    asignacion.save()
                    messages.success(request, f'Equipo "{equipo.nombre}" asignado/actualizado.')
                except ValidationError as e:
                    messages.error(request, str(e.message))

        elif accion == 'eliminar_equipo':
            asignacion_id = request.POST.get('asignacion_id', '').strip()
            AsignacionEquipo.objects.filter(id=asignacion_id, evento=evento).delete()
            messages.warning(request, 'Equipo removido del evento.')

        return redirect('detalle_evento_coordinador', evento_id=evento.id)

    # Recalcular disponibilidad de equipos
    equipos_con_disponibilidad = []
    ids_equipos_asignados = set(asignaciones_equipos.values_list('equipo_id', flat=True))
    for eq in equipos_disponibles:
        disp = eq.cantidad_disponible_en_fecha(
            evento.fecha_montaje_inicio, evento.fecha_desmontaje_fin, evento_excluir_id=evento.id
        )
        equipos_con_disponibilidad.append({
            'equipo': eq,
            'disponible': disp,
            'ya_asignado': eq.id in ids_equipos_asignados,
        })

    # Recalcular luego del posible POST
    asignaciones_catering = AsignacionCatering.objects.filter(evento=evento).select_related('proveedor')
    ids_ya_asignados = set(asignaciones_catering.values_list('proveedor_id', flat=True))
    proveedores_disponibles = ProveedorCatering.objects.filter(activo=True).exclude(id__in=ids_ya_asignados)

    return render(request, 'detalle_evento_coordinador.html', {
        'evento': evento,
        'proveedores_disponibles': proveedores_disponibles,
        'equipos_con_disponibilidad': equipos_con_disponibilidad,
        'asignaciones_catering': asignaciones_catering,
        'asignaciones_equipos': asignaciones_equipos,
        'catering_cotizacion': catering_cotizacion,
        'equipos_cotizacion': equipos_cotizacion,
        'estados_posibles': [
            (estado, label) for estado, label in Evento.Estado.choices
            if evento.puede_cambiar_a(estado)
        ],
    })


# ======================================================
# CALENDARIO
# ======================================================

@login_required(login_url='iniciar_sesion')
def calendario_salones(request):
    # Clientes también pueden ver el calendario (solo lectura + cotizar)
    if not (es_administrador(request.user) or es_coordinador(request.user)
            or requiere_rol(request.user, Usuario.Rol.CLIENTE)):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    salones = Salon.objects.filter(activo=True)
    es_admin = es_administrador(request.user)
    return render(request, 'calendario_salones.html', {'salones': salones, 'es_admin': es_admin})


@login_required(login_url='iniciar_sesion')
def eventos_calendario_json(request):
    """
    Devuelve los eventos en el formato que espera FullCalendar.
    Cada Evento se representa como 3 bloques: montaje, evento, desmontaje.
    """
    if not (es_administrador(request.user) or es_coordinador(request.user)
            or requiere_rol(request.user, Usuario.Rol.CLIENTE)):
        return JsonResponse([], safe=False)

    eventos = Evento.objects.exclude(estado=Evento.Estado.CANCELADO).select_related(
        'salon', 'cotizacion_origen__cliente__user'
    )

    salon_id = request.GET.get('salon')
    if salon_id:
        eventos = eventos.filter(salon_id=salon_id)

    bloques = []
    for ev in eventos:
        cliente_nombre = ev.cotizacion_origen.cliente.user.get_full_name()

        bloques.append({
            'title': f'🕐 Preparación — {ev.salon.nombre}',
            'start': ev.fecha_montaje_inicio.isoformat(),
            'end': ev.fecha_evento_inicio.isoformat(),
            'color': '#FFC107',
            'extendedProps': {'tipo': 'Preparación del salón', 'cliente': cliente_nombre, 'evento_id': ev.id}
        })
        bloques.append({
            'title': f'🎊 {cliente_nombre} — {ev.salon.nombre}',
            'start': ev.fecha_evento_inicio.isoformat(),
            'end': ev.fecha_evento_fin.isoformat(),
            'color': '#0B3C5D',
            'extendedProps': {'tipo': 'Evento', 'cliente': cliente_nombre, 'evento_id': ev.id}
        })
        bloques.append({
            'title': f'🧹 Cierre — {ev.salon.nombre}',
            'start': ev.fecha_evento_fin.isoformat(),
            'end': ev.fecha_desmontaje_fin.isoformat(),
            'color': '#FD7E14',
            'extendedProps': {'tipo': 'Cierre del salón', 'cliente': cliente_nombre, 'evento_id': ev.id}
        })

    return JsonResponse(bloques, safe=False)


# ======================================================
# DISPONIBILIDAD DE SALÓN POR FECHA (JSON para el calendario)
# ======================================================

@login_required(login_url='iniciar_sesion')
def disponibilidad_salon_json(request):
    """
    GET /calendario/disponibilidad/?fecha=YYYY-MM-DD[&salon=<id>]
    Accesible para admin, coordinador y cliente.
    """
    from datetime import date as date_type
    fecha_str = request.GET.get('fecha', '')
    salon_id  = request.GET.get('salon', '')

    if not fecha_str:
        return JsonResponse({'disponible': False, 'motivo': 'Falta el parámetro de fecha.'})

    try:
        fecha = datetime.strptime(fecha_str, '%Y-%m-%d').date()
    except ValueError:
        return JsonResponse({'disponible': False, 'motivo': 'Fecha inválida.'})

    if fecha < date_type.today():
        return JsonResponse({'disponible': False, 'motivo': 'No se pueden registrar cotizaciones en fechas pasadas.'})

    # Si no se especificó salón, la fecha está disponible (se elegirá después)
    if not salon_id:
        return JsonResponse({'disponible': True, 'motivo': ''})

    try:
        salon = Salon.objects.get(id=salon_id, activo=True)
    except Salon.DoesNotExist:
        return JsonResponse({'disponible': False, 'motivo': 'Salón no encontrado.'})

    conflicto = Evento.objects.filter(
        salon=salon,
        estado__in=[
            Evento.Estado.CONFIRMADO,
            Evento.Estado.EN_MONTAJE,
            Evento.Estado.EN_CURSO,
            Evento.Estado.EN_DESMONTAJE,
        ],
        fecha_montaje_inicio__date__lte=fecha,
        fecha_desmontaje_fin__date__gte=fecha,
    ).exists()

    if conflicto:
        return JsonResponse({
            'disponible': False,
            'motivo': f'El salón "{salon.nombre}" ya tiene un evento reservado ese día.'
        })

    return JsonResponse({'disponible': True, 'motivo': ''})


# ======================================================
# DISPOSICIÓN DE MESAS (Coordinador)
# ======================================================

@login_required(login_url='iniciar_sesion')
def disposicion_salon(request, evento_id):
    if not es_coordinador(request.user):
        messages.error(request, 'Esta sección es solo para coordinadores.')
        return redirect('catalogo_salones')

    evento = get_object_or_404(Evento, id=evento_id, coordinador=request.user.usuario)
    disposicion, creada = DisposicionSalon.objects.get_or_create(evento=evento)

    return render(request, 'disposicion_salon.html', {
        'evento': evento,
        'disposicion': disposicion,
        'layout_json': json.dumps(disposicion.layout_json),
    })


@login_required(login_url='iniciar_sesion')
@require_POST
def guardar_disposicion(request, evento_id):
    if not es_coordinador(request.user):
        return JsonResponse({'ok': False, 'error': 'No autorizado'}, status=403)

    evento = get_object_or_404(Evento, id=evento_id, coordinador=request.user.usuario)
    disposicion, creada = DisposicionSalon.objects.get_or_create(evento=evento)

    try:
        data = json.loads(request.body)
        disposicion.layout_json = data.get('layout', [])
        disposicion.save()
        return JsonResponse({'ok': True})
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'ok': False, 'error': 'Datos inválidos'}, status=400)

@login_required(login_url='iniciar_sesion')
def crear_cotizacion_admin(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    clientes = Usuario.objects.filter(rol=Usuario.Rol.CLIENTE)
    salones = Salon.objects.filter(activo=True)
    proveedores_catering = ProveedorCatering.objects.filter(activo=True)
    equipos_audiovisuales = EquipoAudiovisual.objects.filter(activo=True)

    contexto = {
        'clientes': clientes,
        'salones': salones,
        'proveedores_catering': proveedores_catering,
        'equipos_audiovisuales': equipos_audiovisuales,
    }

    if request.method == 'POST':
        cliente_id = request.POST.get('cliente', '')
        salon_id = request.POST.get('salon', '')
        fecha = request.POST.get('fecha_evento_tentativa', '')
        hora_inicio = request.POST.get('hora_inicio_tentativa', '')
        hora_fin = request.POST.get('hora_fin_tentativa', '')
        invitados = request.POST.get('numero_invitados', '')
        precio = request.POST.get('precio_total_estimado', '').strip()
        catering_ids = request.POST.getlist('proveedores_catering')
        equipo_ids = request.POST.getlist('equipos_audiovisuales')

        # --- Validaciones obligatorias ---
        if not cliente_id:
            messages.error(request, 'Debes seleccionar un cliente.')
            return render(request, 'crear_cotizacion_admin.html', contexto)

        if not salon_id:
            messages.error(request, 'Debes seleccionar un salón.')
            return render(request, 'crear_cotizacion_admin.html', contexto)

        cliente = get_object_or_404(Usuario, id=cliente_id, rol=Usuario.Rol.CLIENTE)
        salon = get_object_or_404(Salon, id=salon_id, activo=True)

        if not fecha or not hora_inicio or not hora_fin:
            messages.error(request, 'Debes completar la fecha y ambas horas del evento.')
            return render(request, 'crear_cotizacion_admin.html', contexto)

        if hora_fin <= hora_inicio:
            messages.error(request, 'La hora de fin debe ser posterior a la hora de inicio.')
            return render(request, 'crear_cotizacion_admin.html', contexto)

        # La fecha del evento no puede ser en el pasado
        try:
            fecha_obj = datetime.strptime(fecha, '%Y-%m-%d').date()
            if fecha_obj < timezone.now().date():
                messages.error(request, 'La fecha del evento no puede ser en el pasado.')
                return render(request, 'crear_cotizacion_admin.html', contexto)
        except ValueError:
            messages.error(request, 'La fecha ingresada no es válida.')
            return render(request, 'crear_cotizacion_admin.html', contexto)

        if not invitados.isdigit() or int(invitados) < 1:
            messages.error(request, 'El número de invitados debe ser un entero mayor a cero.')
            return render(request, 'crear_cotizacion_admin.html', contexto)

        invitados = int(invitados)
        if invitados > salon.capacidad:
            messages.error(
                request,
                f'El salón "{salon.nombre}" tiene capacidad para {salon.capacidad} personas, '
                f'no para {invitados}.'
            )
            return render(request, 'crear_cotizacion_admin.html', contexto)

        precio_final = None
        if precio:
            try:
                precio_final = float(precio)
                if precio_final <= 0:
                    raise ValueError
            except ValueError:
                messages.error(request, 'El precio debe ser un número mayor a cero.')
                return render(request, 'crear_cotizacion_admin.html', contexto)

        # --- Validación de choque de horario en el mismo salón (con margen de montaje/desmontaje) ---
        inicio_dt = datetime.combine(fecha_obj, datetime.strptime(hora_inicio, '%H:%M').time())
        fin_dt = datetime.combine(fecha_obj, datetime.strptime(hora_fin, '%H:%M').time())
        margen_montaje = inicio_dt - timedelta(hours=3)
        margen_desmontaje = fin_dt + timedelta(hours=2)

        conflictos = Evento.objects.filter(
            salon=salon,
            estado__in=[Evento.Estado.CONFIRMADO, Evento.Estado.EN_MONTAJE,
                        Evento.Estado.EN_CURSO, Evento.Estado.EN_DESMONTAJE],
        ).exclude(
            fecha_desmontaje_fin__lte=timezone.make_aware(margen_montaje)
        ).exclude(
            fecha_montaje_inicio__gte=timezone.make_aware(margen_desmontaje)
        )

        if conflictos.exists():
            messages.error(
                request,
                f'El salón "{salon.nombre}" ya tiene un evento confirmado que se cruza con '
                f'ese horario (considerando tiempo de montaje y desmontaje). Elige otra fecha/hora.'
            )
            return render(request, 'crear_cotizacion_admin.html', contexto)

        # --- Validar cantidades de equipos elegidos contra el inventario total ---
        equipos_validos = list(EquipoAudiovisual.objects.filter(id__in=equipo_ids, activo=True))
        cantidades_equipo = {}
        for equipo in equipos_validos:
            cantidad_raw = request.POST.get(f'cantidad_equipo_{equipo.id}', '1')
            if not _es_entero_positivo(cantidad_raw):
                messages.error(request, f'La cantidad de "{equipo.nombre}" no es válida.')
                return render(request, 'crear_cotizacion_admin.html', contexto)
            cantidad = int(cantidad_raw)
            if cantidad > equipo.cantidad_total:
                messages.error(
                    request,
                    f'Solo hay {equipo.cantidad_total} unidades de "{equipo.nombre}" en inventario.'
                )
                return render(request, 'crear_cotizacion_admin.html', contexto)
            cantidades_equipo[equipo.id] = cantidad

        # --- Todo válido: se crea la cotización junto con catering y equipos elegidos ---
        with transaction.atomic():
            cotizacion = Cotizacion.objects.create(
                cliente=cliente,
                salon_solicitado=salon,
                fecha_evento_tentativa=fecha_obj,
                hora_inicio_tentativa=hora_inicio,
                hora_fin_tentativa=hora_fin,
                numero_invitados=invitados,
                incluye_catering=bool(catering_ids),
                incluye_audiovisuales=bool(equipo_ids),
                precio_total_estimado=precio_final,
            )

            for proveedor in ProveedorCatering.objects.filter(id__in=catering_ids, activo=True):
                CotizacionCatering.objects.create(cotizacion=cotizacion, proveedor=proveedor)

            for equipo in equipos_validos:
                CotizacionEquipo.objects.create(
                    cotizacion=cotizacion, equipo=equipo, cantidad=cantidades_equipo[equipo.id]
                )

            cotizacion.precio_sugerido = cotizacion.calcular_precio_sugerido()
            cotizacion.save(update_fields=['precio_sugerido'])

        messages.success(request, f'Cotización registrada exitosamente para {cliente.user.get_full_name()}.')
        return redirect('panel_cotizaciones')

    return render(request, 'crear_cotizacion_admin.html', contexto)

@login_required(login_url='iniciar_sesion')
def eliminar_cotizacion(request, cotizacion_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para realizar esta acción.')
        return redirect('catalogo_salones')

    cotizacion = get_object_or_404(Cotizacion, id=cotizacion_id)

    if cotizacion.estado != Cotizacion.Estado.PENDIENTE:
        messages.error(
            request,
            'Solo se pueden eliminar cotizaciones que estén en estado Pendiente.'
        )
        return redirect('panel_cotizaciones')

    cliente_nombre = cotizacion.cliente.user.get_full_name()
    cotizacion.delete()
    messages.success(request, f'Cotización de {cliente_nombre} eliminada correctamente.')
    return redirect('panel_cotizaciones')

@login_required(login_url='iniciar_sesion')
def dashboard_admin(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    anio_actual = timezone.now().year
    anio = request.GET.get('anio', anio_actual)
    try:
        anio = int(anio)
    except ValueError:
        anio = anio_actual

    eventos_validos = Evento.objects.exclude(estado=Evento.Estado.CANCELADO)

    # Años disponibles para el selector (según eventos existentes)
    anios_disponibles = list(
        eventos_validos.annotate(anio_evento=ExtractYear('fecha_evento_inicio'))
        .values_list('anio_evento', flat=True)
        .distinct()
        .order_by('-anio_evento')
    )
    if anio_actual not in anios_disponibles:
        anios_disponibles.insert(0, anio_actual)

    # ---------- 1. Ingresos proyectados por trimestre ----------
    eventos_del_anio = eventos_validos.filter(fecha_evento_inicio__year=anio)

    ingresos_trimestre_query = (
        eventos_del_anio
        .annotate(trimestre=ExtractQuarter('fecha_evento_inicio'))
        .values('trimestre')
        .annotate(total=Sum('precio_final'))
        .order_by('trimestre')
    )

    ingresos_por_trimestre = [0, 0, 0, 0]
    for item in ingresos_trimestre_query:
        ingresos_por_trimestre[item['trimestre'] - 1] = float(item['total'] or 0)

    ingreso_total_anio = sum(ingresos_por_trimestre)

    # ---------- 2. Salones más rentables (histórico) ----------
    salones_rentables = (
        eventos_validos
        .values('salon__nombre')
        .annotate(total_ingresos=Sum('precio_final'), cantidad_eventos=Count('id'))
        .order_by('-total_ingresos')[:10]
    )

    nombres_salones = [s['salon__nombre'] for s in salones_rentables]
    ingresos_salones = [float(s['total_ingresos'] or 0) for s in salones_rentables]

    # ---------- 3. Densidad de eventos por mes (del año seleccionado) ----------
    eventos_por_mes_query = (
        eventos_del_anio
        .annotate(mes=ExtractMonth('fecha_evento_inicio'))
        .values('mes')
        .annotate(cantidad=Count('id'))
        .order_by('mes')
    )

    eventos_por_mes = [0] * 12
    for item in eventos_por_mes_query:
        eventos_por_mes[item['mes'] - 1] = item['cantidad']

    contexto = {
        'anio_seleccionado': anio,
        'anios_disponibles': sorted(set(anios_disponibles), reverse=True),
        'ingresos_por_trimestre': ingresos_por_trimestre,
        'ingreso_total_anio': ingreso_total_anio,
        'nombres_salones': nombres_salones,
        'ingresos_salones': ingresos_salones,
        'eventos_por_mes': eventos_por_mes,
        'total_eventos_anio': sum(eventos_por_mes),
    }
    return render(request, 'dashboard_admin.html', contexto)

@login_required(login_url='iniciar_sesion')
def reporte_pdf(request):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    anio_actual = timezone.now().year
    anio = request.GET.get('anio', anio_actual)
    try:
        anio = int(anio)
    except ValueError:
        anio = anio_actual

    eventos_validos = Evento.objects.exclude(estado=Evento.Estado.CANCELADO)
    eventos_del_anio = eventos_validos.filter(fecha_evento_inicio__year=anio)

    # Ingresos por trimestre
    ingresos_trimestre_query = (
        eventos_del_anio
        .annotate(trimestre=ExtractQuarter('fecha_evento_inicio'))
        .values('trimestre')
        .annotate(total=Sum('precio_final'))
        .order_by('trimestre')
    )
    ingresos_por_trimestre = [0, 0, 0, 0]
    for item in ingresos_trimestre_query:
        ingresos_por_trimestre[item['trimestre'] - 1] = float(item['total'] or 0)

    # Salones más rentables
    salones_rentables = (
        eventos_validos
        .values('salon__nombre')
        .annotate(total_ingresos=Sum('precio_final'), cantidad_eventos=Count('id'))
        .order_by('-total_ingresos')
    )

    # Eventos por mes
    nombres_meses = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
                      'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']
    eventos_por_mes_query = (
        eventos_del_anio
        .annotate(mes=ExtractMonth('fecha_evento_inicio'))
        .values('mes')
        .annotate(cantidad=Count('id'))
        .order_by('mes')
    )
    eventos_por_mes_dict = {item['mes']: item['cantidad'] for item in eventos_por_mes_query}
    eventos_por_mes = [
        {'nombre': nombres_meses[i], 'cantidad': eventos_por_mes_dict.get(i + 1, 0)}
        for i in range(12)
    ]

    contexto = {
        'anio': anio,
        'fecha_generacion': timezone.now(),
        'trimestres': [
            {'nombre': 'Q1 (Enero - Marzo)', 'total': ingresos_por_trimestre[0]},
            {'nombre': 'Q2 (Abril - Junio)', 'total': ingresos_por_trimestre[1]},
            {'nombre': 'Q3 (Julio - Septiembre)', 'total': ingresos_por_trimestre[2]},
            {'nombre': 'Q4 (Octubre - Diciembre)', 'total': ingresos_por_trimestre[3]},
        ],
        'ingreso_total_anio': sum(ingresos_por_trimestre),
        'salones_rentables': salones_rentables,
        'eventos_por_mes': eventos_por_mes,
        'total_eventos_anio': sum(e['cantidad'] for e in eventos_por_mes),
    }
    return render(request, 'reporte_pdf.html', contexto)


# ======================================================
# CLIENTE: dashboard personal y reporte imprimible
# ======================================================

@login_required(login_url='iniciar_sesion')
def dashboard_cliente(request):
    if not requiere_rol(request.user, Usuario.Rol.CLIENTE):
        messages.error(request, 'Esta sección es solo para clientes.')
        return redirect('catalogo_salones')

    usuario = request.user.usuario
    cotizaciones = Cotizacion.objects.filter(cliente=usuario)

    # ---- Tarjetas de resumen ----
    total_cotizaciones   = cotizaciones.count()
    pendientes           = cotizaciones.filter(estado=Cotizacion.Estado.PENDIENTE).count()
    aprobadas            = cotizaciones.filter(estado=Cotizacion.Estado.APROBADA).count()
    rechazadas           = cotizaciones.filter(estado=Cotizacion.Estado.RECHAZADA).count()

    gasto_total = (
        cotizaciones
        .filter(estado=Cotizacion.Estado.APROBADA)
        .aggregate(total=Sum('precio_total_estimado'))['total'] or 0
    )

    # Próximo evento activo (el más cercano en el futuro)
    proximo_evento = (
        Evento.objects
        .filter(
            cotizacion_origen__cliente=usuario,
            estado__in=[Evento.Estado.CONFIRMADO, Evento.Estado.EN_MONTAJE, Evento.Estado.EN_CURSO],
            fecha_evento_inicio__gte=timezone.now(),
        )
        .order_by('fecha_evento_inicio')
        .first()
    )

    # ---- Gráfico 1: estados de cotizaciones (torta) ----
    estados_data = [pendientes, aprobadas, rechazadas]

    # ---- Gráfico 2: gasto por mes (últimos 12 meses) ----
    from datetime import date
    hoy = timezone.now().date()
    meses_labels = []
    gasto_por_mes = []
    for i in range(11, -1, -1):
        # Primer día del mes i meses atrás
        mes_offset = (hoy.month - 1 - i) % 12 + 1
        anio_offset = hoy.year + ((hoy.month - 1 - i) // 12)
        meses_labels.append(
            ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][mes_offset - 1]
            + f' {str(anio_offset)[-2:]}'
        )
        total_mes = (
            cotizaciones
            .filter(
                estado=Cotizacion.Estado.APROBADA,
                fecha_solicitud__year=anio_offset,
                fecha_solicitud__month=mes_offset,
            )
            .aggregate(total=Sum('precio_total_estimado'))['total'] or 0
        )
        gasto_por_mes.append(float(total_mes))

    # ---- Gráfico 3: cotizaciones por mes ----
    cotizaciones_por_mes = []
    for i in range(11, -1, -1):
        mes_offset = (hoy.month - 1 - i) % 12 + 1
        anio_offset = hoy.year + ((hoy.month - 1 - i) // 12)
        cotizaciones_por_mes.append(
            cotizaciones
            .filter(fecha_solicitud__year=anio_offset, fecha_solicitud__month=mes_offset)
            .count()
        )

    import json as _json
    contexto = {
        'total_cotizaciones':  total_cotizaciones,
        'pendientes':          pendientes,
        'aprobadas':           aprobadas,
        'rechazadas':          rechazadas,
        'gasto_total':         gasto_total,
        'proximo_evento':      proximo_evento,
        'estados_data':        _json.dumps(estados_data),
        'meses_labels':        _json.dumps(meses_labels),
        'gasto_por_mes':       _json.dumps(gasto_por_mes),
        'cotizaciones_por_mes':_json.dumps(cotizaciones_por_mes),
    }
    return render(request, 'dashboard_cliente.html', contexto)


@login_required(login_url='iniciar_sesion')
def reporte_pdf_cliente(request):
    if not requiere_rol(request.user, Usuario.Rol.CLIENTE):
        messages.error(request, 'Esta sección es solo para clientes.')
        return redirect('catalogo_salones')

    usuario = request.user.usuario
    cotizaciones = Cotizacion.objects.filter(cliente=usuario).select_related(
        'salon_solicitado'
    ).order_by('-fecha_solicitud')

    aprobadas = cotizaciones.filter(estado=Cotizacion.Estado.APROBADA)
    gasto_total = aprobadas.aggregate(total=Sum('precio_total_estimado'))['total'] or 0

    nombres_meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

    # Gasto por mes agrupado
    from datetime import date
    hoy = timezone.now().date()
    gasto_por_mes_tabla = []
    for i in range(11, -1, -1):
        mes_offset = (hoy.month - 1 - i) % 12 + 1
        anio_offset = hoy.year + ((hoy.month - 1 - i) // 12)
        total_mes = (
            aprobadas
            .filter(fecha_solicitud__year=anio_offset, fecha_solicitud__month=mes_offset)
            .aggregate(total=Sum('precio_total_estimado'))['total'] or 0
        )
        gasto_por_mes_tabla.append({
            'nombre': f"{nombres_meses[mes_offset - 1]} {anio_offset}",
            'total': total_mes,
        })

    contexto = {
        'cotizaciones':       cotizaciones,
        'gasto_total':        gasto_total,
        'total_aprobadas':    aprobadas.count(),
        'total_pendientes':   cotizaciones.filter(estado=Cotizacion.Estado.PENDIENTE).count(),
        'total_rechazadas':   cotizaciones.filter(estado=Cotizacion.Estado.RECHAZADA).count(),
        'gasto_por_mes_tabla':gasto_por_mes_tabla,
        'fecha_generacion':   timezone.now(),
        'cliente_nombre':     usuario.user.get_full_name(),
    }
    return render(request, 'reporte_pdf_cliente.html', contexto)


# ======================================================
# COORDINADOR: dashboard personal y reporte imprimible
# ======================================================

@login_required(login_url='iniciar_sesion')
def dashboard_coordinador(request):
    if not es_coordinador(request.user):
        messages.error(request, 'Esta sección es solo para coordinadores.')
        return redirect('catalogo_salones')

    coordinador = request.user.usuario

    # Todos los eventos asignados a este coordinador
    todos = Evento.objects.filter(coordinador=coordinador).select_related('salon', 'cotizacion_origen__cliente__user')

    total_eventos       = todos.count()
    confirmados         = todos.filter(estado=Evento.Estado.CONFIRMADO).count()
    en_montaje          = todos.filter(estado=Evento.Estado.EN_MONTAJE).count()
    en_curso            = todos.filter(estado=Evento.Estado.EN_CURSO).count()
    en_desmontaje       = todos.filter(estado=Evento.Estado.EN_DESMONTAJE).count()
    finalizados         = todos.filter(estado=Evento.Estado.FINALIZADO).count()
    cancelados          = todos.filter(estado=Evento.Estado.CANCELADO).count()
    activos             = confirmados + en_montaje + en_curso + en_desmontaje

    # Próximo evento (el más cercano en el futuro aún activo)
    proximo = (
        todos
        .filter(
            estado__in=[Evento.Estado.CONFIRMADO, Evento.Estado.EN_MONTAJE, Evento.Estado.EN_CURSO],
            fecha_evento_inicio__gte=timezone.now(),
        )
        .order_by('fecha_evento_inicio')
        .first()
    )

    # Gráfico 1: estados (torta)
    estados_data = [confirmados, en_montaje, en_curso, en_desmontaje, finalizados, cancelados]

    # Gráfico 2: eventos por mes — últimos 12 meses
    from datetime import date as _date
    hoy = timezone.now().date()
    meses_labels = []
    eventos_por_mes = []
    for i in range(11, -1, -1):
        mes_offset  = (hoy.month - 1 - i) % 12 + 1
        anio_offset = hoy.year + ((hoy.month - 1 - i) // 12)
        meses_labels.append(
            ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'][mes_offset - 1]
            + f" {str(anio_offset)[-2:]}"
        )
        eventos_por_mes.append(
            todos.filter(
                fecha_evento_inicio__year=anio_offset,
                fecha_evento_inicio__month=mes_offset,
            ).count()
        )

    # Gráfico 3: ingresos gestionados por mes (eventos finalizados)
    ingresos_por_mes = []
    for i in range(11, -1, -1):
        mes_offset  = (hoy.month - 1 - i) % 12 + 1
        anio_offset = hoy.year + ((hoy.month - 1 - i) // 12)
        total = (
            todos
            .filter(
                estado=Evento.Estado.FINALIZADO,
                fecha_evento_inicio__year=anio_offset,
                fecha_evento_inicio__month=mes_offset,
            )
            .aggregate(t=Sum('precio_final'))['t'] or 0
        )
        ingresos_por_mes.append(float(total))

    import json as _json
    contexto = {
        'total_eventos':    total_eventos,
        'activos':          activos,
        'finalizados':      finalizados,
        'cancelados':       cancelados,
        'proximo':          proximo,
        'estados_data':     _json.dumps(estados_data),
        'meses_labels':     _json.dumps(meses_labels),
        'eventos_por_mes':  _json.dumps(eventos_por_mes),
        'ingresos_por_mes': _json.dumps(ingresos_por_mes),
    }
    return render(request, 'dashboard_coordinador.html', contexto)


@login_required(login_url='iniciar_sesion')
def reporte_pdf_coordinador(request):
    if not es_coordinador(request.user):
        messages.error(request, 'Esta sección es solo para coordinadores.')
        return redirect('catalogo_salones')

    coordinador = request.user.usuario
    todos = Evento.objects.filter(coordinador=coordinador).select_related(
        'salon', 'cotizacion_origen__cliente__user'
    ).order_by('-fecha_evento_inicio')

    nombres_meses = ['Enero','Febrero','Marzo','Abril','Mayo','Junio',
                     'Julio','Agosto','Septiembre','Octubre','Noviembre','Diciembre']

    from datetime import date as _date
    hoy = timezone.now().date()
    eventos_por_mes_tabla = []
    for i in range(11, -1, -1):
        mes_offset  = (hoy.month - 1 - i) % 12 + 1
        anio_offset = hoy.year + ((hoy.month - 1 - i) // 12)
        cant = todos.filter(
            fecha_evento_inicio__year=anio_offset,
            fecha_evento_inicio__month=mes_offset,
        ).count()
        eventos_por_mes_tabla.append({
            'nombre': f"{nombres_meses[mes_offset - 1]} {anio_offset}",
            'cantidad': cant,
        })

    finalizados = todos.filter(estado=Evento.Estado.FINALIZADO)
    ingresos_gestionados = finalizados.aggregate(t=Sum('precio_final'))['t'] or 0

    contexto = {
        'eventos':               todos,
        'total_eventos':         todos.count(),
        'total_finalizados':     finalizados.count(),
        'total_activos':         todos.filter(estado__in=[
                                     Evento.Estado.CONFIRMADO, Evento.Estado.EN_MONTAJE,
                                     Evento.Estado.EN_CURSO, Evento.Estado.EN_DESMONTAJE,
                                 ]).count(),
        'total_cancelados':      todos.filter(estado=Evento.Estado.CANCELADO).count(),
        'ingresos_gestionados':  ingresos_gestionados,
        'eventos_por_mes_tabla': eventos_por_mes_tabla,
        'coordinador_nombre':    coordinador.user.get_full_name(),
        'fecha_generacion':      timezone.now(),
    }
    return render(request, 'reporte_pdf_coordinador.html', contexto)


# ======================================================
# ADMINISTRADOR: editar cotización pendiente
# ======================================================

@login_required(login_url='iniciar_sesion')
def editar_cotizacion_admin(request, cotizacion_id):
    if not es_administrador(request.user):
        messages.error(request, 'No tienes permiso para acceder a esta sección.')
        return redirect('catalogo_salones')

    cotizacion = get_object_or_404(Cotizacion, id=cotizacion_id)

    if cotizacion.estado != Cotizacion.Estado.PENDIENTE:
        messages.error(request, 'Solo se pueden editar cotizaciones en estado Pendiente.')
        return redirect('panel_cotizaciones')

    clientes              = Usuario.objects.filter(rol=Usuario.Rol.CLIENTE)
    salones               = Salon.objects.filter(activo=True)
    proveedores_catering  = ProveedorCatering.objects.filter(activo=True)
    equipos_audiovisuales = EquipoAudiovisual.objects.filter(activo=True)

    # IDs ya seleccionados en la cotización (para pre-marcar checkboxes)
    catering_ids_actuales = list(cotizacion.catering_seleccionado.values_list('proveedor_id', flat=True))
    equipos_actuales      = {ce.equipo_id: ce.cantidad for ce in cotizacion.equipos_seleccionados.all()}

    import json as _json
    contexto = {
        'clientes':              clientes,
        'salones':               salones,
        'proveedores_catering':  proveedores_catering,
        'equipos_audiovisuales': equipos_audiovisuales,
        'cotizacion':            cotizacion,
        'catering_ids_actuales': catering_ids_actuales,
        'equipos_actuales':      equipos_actuales,
        'equipos_actuales_json': _json.dumps(equipos_actuales),
        'modo_edicion':          True,
    }

    if request.method == 'POST':
        cliente_id    = request.POST.get('cliente', '')
        salon_id      = request.POST.get('salon', '')
        fecha         = request.POST.get('fecha_evento_tentativa', '')
        hora_inicio   = request.POST.get('hora_inicio_tentativa', '')
        hora_fin      = request.POST.get('hora_fin_tentativa', '')
        invitados     = request.POST.get('numero_invitados', '')
        catering_ids  = request.POST.getlist('proveedores_catering')
        equipo_ids    = request.POST.getlist('equipos_audiovisuales')

        if not cliente_id or not salon_id or not fecha or not hora_inicio or not hora_fin:
            messages.error(request, 'Completa todos los campos obligatorios.')
            return render(request, 'editar_cotizacion_admin.html', contexto)

        if hora_fin <= hora_inicio:
            messages.error(request, 'La hora de fin debe ser posterior a la hora de inicio.')
            return render(request, 'editar_cotizacion_admin.html', contexto)

        try:
            fecha_obj = datetime.strptime(fecha, '%Y-%m-%d').date()
            if fecha_obj < timezone.now().date():
                messages.error(request, 'La fecha del evento no puede ser en el pasado.')
                return render(request, 'editar_cotizacion_admin.html', contexto)
        except ValueError:
            messages.error(request, 'La fecha ingresada no es válida.')
            return render(request, 'editar_cotizacion_admin.html', contexto)

        if not invitados.isdigit() or int(invitados) < 1:
            messages.error(request, 'El número de invitados debe ser un entero mayor a cero.')
            return render(request, 'editar_cotizacion_admin.html', contexto)

        cliente = get_object_or_404(Usuario, id=cliente_id, rol=Usuario.Rol.CLIENTE)
        salon   = get_object_or_404(Salon, id=salon_id, activo=True)
        invitados_int = int(invitados)

        if invitados_int > salon.capacidad:
            messages.error(request, f'El salón "{salon.nombre}" tiene capacidad para {salon.capacidad} personas.')
            return render(request, 'editar_cotizacion_admin.html', contexto)

        with transaction.atomic():
            cotizacion.cliente              = cliente
            cotizacion.salon_solicitado     = salon
            cotizacion.fecha_evento_tentativa   = fecha_obj
            cotizacion.hora_inicio_tentativa    = hora_inicio
            cotizacion.hora_fin_tentativa       = hora_fin
            cotizacion.numero_invitados         = invitados_int
            cotizacion.incluye_catering         = bool(catering_ids)
            cotizacion.incluye_audiovisuales    = bool(equipo_ids)
            cotizacion.save()

            # Reemplazar catering
            cotizacion.catering_seleccionado.all().delete()
            for pid in catering_ids:
                proveedor = ProveedorCatering.objects.filter(id=pid, activo=True).first()
                if proveedor:
                    CotizacionCatering.objects.create(cotizacion=cotizacion, proveedor=proveedor)

            # Reemplazar equipos
            cotizacion.equipos_seleccionados.all().delete()
            for eid in equipo_ids:
                equipo = EquipoAudiovisual.objects.filter(id=eid, activo=True).first()
                if equipo:
                    cantidad = request.POST.get(f'cantidad_equipo_{eid}', 1)
                    CotizacionEquipo.objects.create(
                        cotizacion=cotizacion, equipo=equipo,
                        cantidad=int(cantidad) if str(cantidad).isdigit() else 1
                    )

            cotizacion.precio_sugerido = cotizacion.calcular_precio_sugerido()
            cotizacion.precio_total_estimado = cotizacion.precio_sugerido
            cotizacion.save(update_fields=['precio_sugerido', 'precio_total_estimado'])

        messages.success(request, 'Cotización actualizada correctamente.')
        return redirect('panel_cotizaciones')

    return render(request, 'editar_cotizacion_admin.html', contexto)
