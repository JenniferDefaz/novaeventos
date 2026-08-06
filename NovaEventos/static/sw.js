/* Service Worker - NovaEventos PWA
   Estrategia: Cache First para static, Network First para paginas.
   Scope: raiz del dominio (/sw.js)
*/

const CACHE_VERSION = 'v4';
const CACHE_STATIC  = 'novaeventos-static-' + CACHE_VERSION;
const CACHE_PAGES   = 'novaeventos-pages-'  + CACHE_VERSION;

const PRECACHE_URLS = [
  '/',
  '/salones/',
  '/login/',
  '/static/styles/bootstrap-4.1.2/bootstrap.min.css',
  '/static/plugins/font-awesome-4.7.0/css/font-awesome.min.css',
  '/static/styles/main_styles.css',
  '/static/styles/responsive.css',
  '/static/js/jquery-3.2.1.min.js',
  '/static/images/icon-192x192.png',
  '/static/images/icon-512x512.png',
];

/* ---- Instalacion ---- */
self.addEventListener('install', function(event) {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_STATIC).then(function(cache) {
      return Promise.allSettled(
        PRECACHE_URLS.map(function(url) {
          return cache.add(new Request(url, { cache: 'reload' })).catch(function() {});
        })
      );
    })
  );
});

/* ---- Activacion: limpiar caches viejos ---- */
self.addEventListener('activate', function(event) {
  event.waitUntil(
    caches.keys().then(function(keys) {
      return Promise.all(
        keys.filter(function(k) {
          return k !== CACHE_STATIC && k !== CACHE_PAGES;
        }).map(function(k) {
          return caches.delete(k);
        })
      );
    }).then(function() {
      return self.clients.claim();
    })
  );
});

/* ---- Fetch ---- */
self.addEventListener('fetch', function(event) {
  if (event.request.method !== 'GET') return;

  var url = new URL(event.request.url);
  if (url.origin !== location.origin) return;

  if (url.pathname.startsWith('/admin/') ||
      url.pathname.startsWith('/media/') ||
      url.pathname.includes('/json/')    ||
      url.pathname.includes('/disponibilidad/')) return;

  /* Archivos estaticos -> Cache First */
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(function(cached) {
        if (cached) return cached;
        return fetch(event.request).then(function(res) {
          if (res.ok) {
            caches.open(CACHE_STATIC).then(function(c) { c.put(event.request, res.clone()); });
          }
          return res;
        });
      })
    );
    return;
  }

  /* Paginas -> Network First con fallback offline */
  event.respondWith(
    fetch(event.request).then(function(res) {
      if (res.ok) {
        caches.open(CACHE_PAGES).then(function(c) { c.put(event.request, res.clone()); });
      }
      return res;
    }).catch(function() {
      return caches.match(event.request).then(function(cached) {
        if (cached) return cached;
        return new Response(
          '<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">' +
          '<meta name="viewport" content="width=device-width,initial-scale=1">' +
          '<title>Sin conexion - NovaEventos</title>' +
          '<style>' +
          'body{font-family:Arial,sans-serif;text-align:center;padding:60px 20px;background:#2a2929;color:#f0e9e3;}' +
          'h1{color:#D4AF37;font-size:2rem;margin-bottom:10px;}' +
          'p{color:#c9a898;margin:8px 0;}' +
          'a{display:inline-block;margin-top:20px;background:#D4AF37;color:#2a2929;padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:700;}' +
          '</style></head>' +
          '<body><h1>Sin conexion</h1><p>No hay internet en este momento.</p>' +
          '<p>Revisa tu conexion e intenta de nuevo.</p>' +
          '<a href="/">Reintentar</a></body></html>',
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        );
      });
    })
  );
});

/* ---- Notificaciones Push ---- */
self.addEventListener('push', function(event) {
  var data    = event.data ? event.data.json() : {};
  var title   = data.title || 'NovaEventos';
  var options = {
    body:    data.body  || 'Tienes una nueva notificacion.',
    icon:    '/static/images/icon-192x192.png',
    badge:   '/static/images/icon-96x96.png',
    vibrate: [200, 100, 200],
    data:    { url: data.url || '/' },
    actions: [
      { action: 'open',    title: 'Ver ahora' },
      { action: 'dismiss', title: 'Cerrar'    },
    ],
  };
  event.waitUntil(self.registration.showNotification(title, options));
});

/* ---- Clic en notificacion ---- */
self.addEventListener('notificationclick', function(event) {
  event.notification.close();
  if (event.action === 'dismiss') return;
  var url = (event.notification.data && event.notification.data.url) ? event.notification.data.url : '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function(list) {
      for (var i = 0; i < list.length; i++) {
        if (list[i].url.includes(url) && 'focus' in list[i]) return list[i].focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
