"""
URL configuration for NovaEventos project.
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
from django.http import HttpResponse
import os


def serve_sw(request):
    """Sirve el Service Worker con Content-Type correcto y UTF-8."""
    sw_path = os.path.join(settings.BASE_DIR, 'NovaEventos', 'static', 'sw.js')
    with open(sw_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(
        content,
        content_type='application/javascript; charset=utf-8',
        headers={
            'Service-Worker-Allowed': '/',
            'Cache-Control': 'no-cache, no-store, must-revalidate',
        }
    )


def serve_manifest(request):
    """Sirve el manifest.json con Content-Type correcto y UTF-8."""
    manifest_path = os.path.join(settings.BASE_DIR, 'NovaEventos', 'static', 'manifest.json')
    with open(manifest_path, 'r', encoding='utf-8') as f:
        content = f.read()
    return HttpResponse(
        content,
        content_type='application/manifest+json; charset=utf-8',
    )


urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('eventos.urls')),
    # Media files — siempre disponibles incluso con DEBUG=False
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    # PWA — SW y manifest servidos desde la raíz con encoding correcto
    path('sw.js', serve_sw, name='service_worker'),
    path('manifest.json', serve_manifest, name='manifest'),
]
