# Solución: Migración de SQLite a PostgreSQL

## Problema
Después de cambiar la base de datos de SQLite a PostgreSQL, la base de datos quedó vacía (sin usuarios, sin datos).

## Causa
Al cambiar el `DATABASE_URL` en `.env`, Django ahora se conecta a PostgreSQL pero las tablas están vacías porque:
1. Las migraciones NO se corrieron en PostgreSQL
2. Los datos de SQLite NO se migraron automáticamente

---

## SOLUCIÓN PASO A PASO

### 1. Verificar que PostgreSQL está corriendo
```bash
sudo systemctl status postgresql
# Si no está activo:
# sudo systemctl start postgresql
```

### 2. Correr las migraciones en PostgreSQL
```bash
cd /home/jenniferdefaz/django/NovaEventos
python3 manage.py migrate
```

Esto creará todas las tablas en la base de datos `novaeventos_db`.

### 3. Crear el superusuario admin
```bash
python3 manage.py createsuperuser
```

Cuando te pida los datos, usa:
- **Username**: `admin`
- **Email**: `admin@novaeventos.com`
- **Password**: `admin123` (o el que prefieras)

### 4. Crear el objeto Usuario asociado (perfil extendido)

Ejecuta este script en el shell de Django:

```bash
python3 manage.py shell
```

Dentro del shell, copia y pega esto:

```python
from django.contrib.auth.models import User
from eventos.models import Usuario

# Obtener el superusuario que acabas de crear
admin_user = User.objects.get(username='admin')

# Crear el objeto Usuario asociado (perfil extendido con rol)
if not hasattr(admin_user, 'usuario'):
    Usuario.objects.create(
        user=admin_user,
        cedula='1700000000',
        telefono='0999999999',
        rol='ADMINISTRADOR'
    )
    print("✓ Objeto Usuario creado para admin")
else:
    print("✓ admin ya tiene objeto Usuario")

# Verificar
print(f"Usuario: {admin_user.username}")
print(f"Rol: {admin_user.usuario.get_rol_display()}")
print(f"Es admin: {admin_user.usuario.es_administrador}")

# Salir del shell
exit()
```

### 5. Iniciar el servidor y probar
```bash
python3 manage.py runserver 0.0.0.0:8003
```

Abre el navegador en: http://127.0.0.1:8003/login/

**Credenciales:**
- Usuario: `admin`
- Contraseña: `admin123`

---

## OPCIÓN ALTERNATIVA: Script automático

Si prefieres usar un script, ejecuta:

```bash
cd /home/jenniferdefaz/django/NovaEventos
python3 crear_superusuario.py
```

Este script:
- Crea el usuario `admin` si no existe
- Actualiza la contraseña a `admin123` si ya existe
- Crea el objeto `Usuario` con rol `ADMINISTRADOR`

---

## Migrar datos desde SQLite (OPCIONAL)

Si quieres recuperar los datos de la base SQLite anterior:

### 1. Hacer backup de datos desde SQLite
```bash
# Asegúrate de que .env apunte a SQLite temporalmente
# DATABASE_URL=sqlite:///bdd_nova_eventos.db

python3 manage.py dumpdata --exclude auth.permission --exclude contenttypes > backup_sqlite.json
```

### 2. Volver a PostgreSQL
```bash
# Edita .env y vuelve a:
# DATABASE_URL=postgres://novaeventos_user:Nova1234@localhost:5432/novaeventos_db
```

### 3. Cargar datos en PostgreSQL
```bash
python3 manage.py loaddata backup_sqlite.json
```

⚠️ **ADVERTENCIA**: Esto puede fallar si hay conflictos de IDs o dependencias. Es mejor empezar con BD limpia.

---

## Verificación final

Ejecuta esto para confirmar que todo está bien:

```bash
python3 -c "
import os, django
os.environ['DJANGO_SETTINGS_MODULE'] = 'NovaEventos.settings'
django.setup()

from django.contrib.auth.models import User
from eventos.models import Usuario

admins = User.objects.filter(is_superuser=True)
print(f'Superusuarios encontrados: {admins.count()}')
for u in admins:
    print(f'  - {u.username} ({u.email})')
    try:
        print(f'    Rol: {u.usuario.get_rol_display()}')
    except:
        print(f'    ⚠️  Sin objeto Usuario asociado')
"
```

Deberías ver:
```
Superusuarios encontrados: 1
  - admin (admin@novaeventos.com)
    Rol: Administrador
```

---

## Resumen

**TU .ENV ACTUAL:**
```
DATABASE_URL=postgres://novaeventos_user:Nova1234@localhost:5432/novaeventos_db
```

**CREDENCIALES POR DEFECTO:**
- Admin: `admin` / `admin123`
- Coordinador1: `coordinador1` / `Nova2024*`
- Coordinador2: `coordinador2` / `Nova2024*`

Después de migrar, solo existirá el admin. Los coordinadores y clientes deberás crearlos de nuevo desde el panel de Django admin o mediante registros.
