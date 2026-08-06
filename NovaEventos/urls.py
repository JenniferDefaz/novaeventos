"""
URL configuration for NovaEventos project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include, re_path
from django.conf import settings
from django.views.static import serve
import os

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('eventos.urls')),
    # Servir archivos media siempre, incluso con DEBUG=False
    re_path(r'^media/(?P<path>.*)$', serve, {'document_root': settings.MEDIA_ROOT}),
    # PWA: sw.js y manifest.json deben estar en la raíz del sitio
    re_path(r'^sw\.js$', serve, {
        'document_root': os.path.join(settings.BASE_DIR, 'NovaEventos', 'static'),
        'path': 'sw.js'
    }),
    re_path(r'^manifest\.json$', serve, {
        'document_root': os.path.join(settings.BASE_DIR, 'NovaEventos', 'static'),
        'path': 'manifest.json'
    }),
]







