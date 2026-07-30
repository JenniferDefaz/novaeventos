# Create your models here.
from django.db import models
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils import timezone


class Usuario(models.Model):
    class Rol(models.TextChoices):
        CLIENTE = 'CLIENTE', 'Cliente'
        ADMINISTRADOR = 'ADMINISTRADOR', 'Administrador'
        COORDINADOR = 'COORDINADOR', 'Coordinador de Eventos'

    user = models.OneToOneField(User, on_delete=models.CASCADE)
    rol = models.CharField(max_length=15, choices=Rol.choices)
    cedula = models.CharField(max_length=10, unique=True, null=True, blank=True)
    telefono = models.CharField(max_length=10, blank=True)

    class Meta:
        verbose_name = 'Usuario'
        verbose_name_plural = 'Usuarios'

    def __str__(self):
        return f'{self.user.get_full_name() or self.user.username} ({self.rol})'

    @property
    def es_cliente(self):
        return self.rol == self.Rol.CLIENTE

    @property
    def es_administrador(self):
        return self.rol == self.Rol.ADMINISTRADOR

    @property
    def es_coordinador(self):
        return self.rol == self.Rol.COORDINADOR


class Salon(models.Model):
    nombre = models.CharField(max_length=100, unique=True)
    capacidad = models.PositiveIntegerField(help_text='Número máximo de invitados')
    precio_base = models.DecimalField(max_digits=10, decimal_places=2)
    descripcion = models.TextField(blank=True)
    activo = models.BooleanField(default=True)
    imagen = models.ImageField(upload_to='salones/', null=True, blank=True)

    class Meta:
        ordering = ['nombre']
        verbose_name = 'Salón'
        verbose_name_plural = 'Salones'

    def __str__(self):
        return f'{self.nombre} (cap. {self.capacidad})'


class ProveedorCatering(models.Model):
    nombre_empresa = models.CharField(max_length=150)
    contacto = models.CharField(max_length=100)
    telefono = models.CharField(max_length=10)
    especialidad = models.CharField(max_length=150, help_text='Ej: comida gourmet, bocaditos, bar')
    precio_por_persona = models.DecimalField(max_digits=8, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['nombre_empresa']
        verbose_name = 'Proveedor de Catering'
        verbose_name_plural = 'Proveedores de Catering'

    def __str__(self):
        return self.nombre_empresa


class EquipoAudiovisual(models.Model):
    class Categoria(models.TextChoices):
        PROYECTOR = 'PROYECTOR', 'Proyector'
        SONIDO = 'SONIDO', 'Sistema de sonido'
        ILUMINACION = 'ILUMINACION', 'Iluminación'
        MICROFONO = 'MICROFONO', 'Micrófono'
        PANTALLA = 'PANTALLA', 'Pantalla'

    nombre = models.CharField(max_length=100)
    categoria = models.CharField(max_length=15, choices=Categoria.choices)
    cantidad_total = models.PositiveIntegerField(help_text='Unidades totales disponibles en inventario')
    precio_unitario = models.DecimalField(max_digits=8, decimal_places=2)
    activo = models.BooleanField(default=True)

    class Meta:
        ordering = ['categoria', 'nombre']
        verbose_name = 'Equipo Audiovisual'
        verbose_name_plural = 'Equipos Audiovisuales'

    def __str__(self):
        return f'{self.nombre} ({self.cantidad_total} disponibles)'

    def cantidad_disponible_en_fecha(self, fecha_inicio, fecha_fin, evento_excluir_id=None):
        """
        Calcula cuántas unidades quedan libres de este equipo, considerando
        todos los eventos que se traslapan con el rango de fechas dado.
        """
        asignaciones = AsignacionEquipo.objects.filter(
            equipo=self,
            evento__estado__in=[Evento.Estado.CONFIRMADO, Evento.Estado.EN_MONTAJE,
                                 Evento.Estado.EN_CURSO, Evento.Estado.EN_DESMONTAJE],
        ).exclude(
            evento__fecha_desmontaje_fin__lte=fecha_inicio
        ).exclude(
            evento__fecha_montaje_inicio__gte=fecha_fin
        )

        if evento_excluir_id:
            asignaciones = asignaciones.exclude(evento_id=evento_excluir_id)

        comprometido = sum(a.cantidad_asignada for a in asignaciones)
        return self.cantidad_total - comprometido


class Cotizacion(models.Model):
    class Estado(models.TextChoices):
        PENDIENTE = 'PENDIENTE', 'Pendiente'
        APROBADA = 'APROBADA', 'Aprobada'
        RECHAZADA = 'RECHAZADA', 'Rechazada'

    cliente = models.ForeignKey(
        Usuario, on_delete=models.PROTECT, related_name='cotizaciones',
        limit_choices_to={'rol': Usuario.Rol.CLIENTE}
    )
    salon_solicitado = models.ForeignKey(Salon, on_delete=models.PROTECT, related_name='cotizaciones')

    fecha_evento_tentativa = models.DateField()
    hora_inicio_tentativa = models.TimeField()
    hora_fin_tentativa = models.TimeField()
    numero_invitados = models.PositiveIntegerField()

    incluye_catering = models.BooleanField(default=False)
    # ANTES: proveedor_catering = models.ForeignKey(ProveedorCatering, on_delete=models.SET_NULL,
    #                                                null=True, blank=True, related_name='cotizaciones')
    # AHORA: M2M -> se pueden elegir varios proveedores en la misma cotización,
    # igual que ya funciona con equipos_deseados / CotizacionEquipo.
    proveedores_catering = models.ManyToManyField(
        ProveedorCatering, through='CotizacionCatering', related_name='cotizaciones', blank=True
    )

    incluye_audiovisuales = models.BooleanField(default=False)
    equipos_deseados = models.ManyToManyField(
        EquipoAudiovisual, through='CotizacionEquipo', related_name='cotizaciones', blank=True
    )

    precio_sugerido = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    precio_total_estimado = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    comentario_admin = models.TextField(blank=True)

    fecha_solicitud = models.DateTimeField(auto_now_add=True)
    fecha_respuesta = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ['-fecha_solicitud']
        verbose_name = 'Cotización'
        verbose_name_plural = 'Cotizaciones'

    def __str__(self):
        return f'Cotización #{self.id} - {self.cliente} ({self.estado})'

    def calcular_precio_sugerido(self):
        """
        Calcula el precio estimado según salón, catering y equipos elegidos.
        No incluye el precio final que el admin decida; solo es una base de cálculo.
        """
        total = self.salon_solicitado.precio_base

        if self.incluye_catering:
            for item in self.catering_seleccionado.select_related('proveedor'):
                total += self.numero_invitados * item.proveedor.precio_por_persona

        if self.incluye_audiovisuales:
            for asignacion in self.equipos_seleccionados.select_related('equipo'):
                total += asignacion.equipo.precio_unitario * asignacion.cantidad

        return total


class CotizacionCatering(models.Model):
    """Proveedor(es) de catering elegidos para una cotización. Permite más de uno."""
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name='catering_seleccionado')
    proveedor = models.ForeignKey(ProveedorCatering, on_delete=models.PROTECT)

    class Meta:
        unique_together = ('cotizacion', 'proveedor')
        verbose_name = 'Proveedor de Catering en Cotización'
        verbose_name_plural = 'Proveedores de Catering en Cotizaciones'

    def __str__(self):
        return f'{self.cotizacion} - {self.proveedor}'


class CotizacionEquipo(models.Model):
    cotizacion = models.ForeignKey(Cotizacion, on_delete=models.CASCADE, related_name='equipos_seleccionados')
    equipo = models.ForeignKey(EquipoAudiovisual, on_delete=models.PROTECT)
    cantidad = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('cotizacion', 'equipo')
        verbose_name = 'Equipo Deseado en Cotización'
        verbose_name_plural = 'Equipos Deseados en Cotizaciones'

    def __str__(self):
        return f'{self.cotizacion} - {self.equipo} x{self.cantidad}'


class Evento(models.Model):
    class Estado(models.TextChoices):
        CONFIRMADO = 'CONFIRMADO', 'Confirmado'
        EN_MONTAJE = 'EN_MONTAJE', 'En montaje'
        EN_CURSO = 'EN_CURSO', 'En curso'
        EN_DESMONTAJE = 'EN_DESMONTAJE', 'En desmontaje'
        FINALIZADO = 'FINALIZADO', 'Finalizado'
        CANCELADO = 'CANCELADO', 'Cancelado'

    TRANSICIONES_VALIDAS = {
        Estado.CONFIRMADO: [Estado.EN_MONTAJE, Estado.CANCELADO],
        Estado.EN_MONTAJE: [Estado.EN_CURSO],
        Estado.EN_CURSO: [Estado.EN_DESMONTAJE],
        Estado.EN_DESMONTAJE: [Estado.FINALIZADO],
        Estado.FINALIZADO: [],
        Estado.CANCELADO: [],
    }

    cotizacion_origen = models.OneToOneField(Cotizacion, on_delete=models.PROTECT, related_name='evento')
    salon = models.ForeignKey(Salon, on_delete=models.PROTECT, related_name='eventos')
    coordinador = models.ForeignKey(
        Usuario, on_delete=models.SET_NULL, null=True, blank=True,
        related_name='eventos_asignados',
        limit_choices_to={'rol': Usuario.Rol.COORDINADOR}
    )
    proveedores_catering = models.ManyToManyField(
        ProveedorCatering, through='AsignacionCatering', related_name='eventos', blank=True
    )
    equipos = models.ManyToManyField(
        EquipoAudiovisual, through='AsignacionEquipo', related_name='eventos', blank=True
    )

    fecha_montaje_inicio = models.DateTimeField()
    fecha_evento_inicio = models.DateTimeField()
    fecha_evento_fin = models.DateTimeField()
    fecha_desmontaje_fin = models.DateTimeField()

    precio_final = models.DecimalField(max_digits=10, decimal_places=2)
    estado = models.CharField(max_length=15, choices=Estado.choices, default=Estado.CONFIRMADO)
    factura_pdf = models.FileField(upload_to='facturas_pdf/', null=True, blank=True)

    fecha_creacion = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['fecha_evento_inicio']
        verbose_name = 'Evento'
        verbose_name_plural = 'Eventos'

    def __str__(self):
        return f'{self.cotizacion_origen.cliente} - {self.salon} ({self.fecha_evento_inicio:%d/%m/%Y})'

    def clean(self):
        """Valida que las fechas tengan sentido y que no haya conflicto de salón."""
        if self.fecha_montaje_inicio >= self.fecha_evento_inicio:
            raise ValidationError('El montaje debe iniciar antes del evento.')
        if self.fecha_evento_inicio >= self.fecha_evento_fin:
            raise ValidationError('La hora de inicio debe ser antes que la de fin.')
        if self.fecha_evento_fin >= self.fecha_desmontaje_fin:
            raise ValidationError('El desmontaje debe terminar después del evento.')

        conflictos = Evento.objects.filter(
            salon=self.salon,
            estado__in=[self.Estado.CONFIRMADO, self.Estado.EN_MONTAJE,
                        self.Estado.EN_CURSO, self.Estado.EN_DESMONTAJE],
        ).exclude(
            fecha_desmontaje_fin__lte=self.fecha_montaje_inicio
        ).exclude(
            fecha_montaje_inicio__gte=self.fecha_desmontaje_fin
        )
        if self.pk:
            conflictos = conflictos.exclude(pk=self.pk)

        if conflictos.exists():
            raise ValidationError(
                f'El salón "{self.salon}" ya está comprometido en ese rango de fechas '
                f'(considerando montaje y desmontaje).'
            )

    def puede_cambiar_a(self, nuevo_estado):
        return nuevo_estado in self.TRANSICIONES_VALIDAS.get(self.estado, [])

    def cambiar_estado(self, nuevo_estado):
        if not self.puede_cambiar_a(nuevo_estado):
            raise ValidationError(
                f'No se puede cambiar de "{self.get_estado_display()}" a '
                f'"{dict(self.Estado.choices).get(nuevo_estado, nuevo_estado)}".'
            )
        self.estado = nuevo_estado
        self.save()


class AsignacionCatering(models.Model):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE)
    proveedor = models.ForeignKey(ProveedorCatering, on_delete=models.PROTECT)
    tipo_servicio = models.CharField(max_length=100, help_text='Ej: comida principal, postres, bar')

    class Meta:
        unique_together = ('evento', 'proveedor', 'tipo_servicio')
        verbose_name = 'Asignación de Catering'
        verbose_name_plural = 'Asignaciones de Catering'

    def __str__(self):
        return f'{self.evento} - {self.proveedor} ({self.tipo_servicio})'


class AsignacionEquipo(models.Model):
    evento = models.ForeignKey(Evento, on_delete=models.CASCADE)
    equipo = models.ForeignKey(EquipoAudiovisual, on_delete=models.PROTECT)
    cantidad_asignada = models.PositiveIntegerField(default=1)

    class Meta:
        unique_together = ('evento', 'equipo')
        verbose_name = 'Asignación de Equipo'
        verbose_name_plural = 'Asignaciones de Equipos'

    def __str__(self):
        return f'{self.evento} - {self.equipo} x{self.cantidad_asignada}'

    def clean(self):
        disponible = self.equipo.cantidad_disponible_en_fecha(
            self.evento.fecha_montaje_inicio,
            self.evento.fecha_desmontaje_fin,
            evento_excluir_id=self.evento_id
        )
        if self.cantidad_asignada > disponible:
            raise ValidationError(
                f'Solo hay {disponible} unidades disponibles de "{self.equipo}" en esas fechas.'
            )


class DisposicionSalon(models.Model):
    evento = models.OneToOneField(Evento, on_delete=models.CASCADE, related_name='disposicion')
    layout_json = models.JSONField(default=list, blank=True)
    fecha_ultima_edicion = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Disposición de Salón'
        verbose_name_plural = 'Disposiciones de Salón'

    def __str__(self):
        return f'Disposición de {self.evento}'