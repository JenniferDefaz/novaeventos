/**
 * Service Worker — NovaEventos PWA
 * Estrategia: Cache First para assets estáticos, Network First para páginas.
 * Scope: raíz del dominio, servido desde /sw.js
 */

const CACHE_VERSION = 'v3';
const CACHE_STATIC  = `novaeventos-static-${CACHE_VERSION}`;
const CACHE_PAGES   = `novaeventos-pages-${CACHE_VERSION}`;

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

// ---- Instalación ----
self.addEventListener('install', event => {
  self.skipWaiting();
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache =>
      Promise.allSettled(
        PRECACHE_URLS.map(url =>
          cache.add(new Request(url, { cache: 'reload' })).catch(() => {})
        )
      )
    )
  );
});

// ---- Activación: limpiar caches viejos ----
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys()
      .then(keys => Promise.all(
        keys.filter(k => k !== CACHE_STATIC && k !== CACHE_PAGES)
            .map(k => caches.delete(k))
      ))
      .then(() => self.clients.claim())
  );
});

// ---- Fetch ----
self.addEventListener('fetch', event => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);
  if (url.origin !== location.origin) return;
  // No interceptar admin, media ni APIs JSON
  if (url.pathname.startsWith('/admin/') ||
      url.pathname.startsWith('/media/')  ||
      url.pathname.includes('/json/')     ||
      url.pathname.includes('/disponibilidad/')) return;

  // Estáticos → Cache First
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(res => {
          if (res.ok) caches.open(CACHE_STATIC).then(c => c.put(event.request, res.clone()));
          return res;
        });
      })
    );
    return;
  }

  // Páginas → Network First con fallback offline
  event.respondWith(
    fetch(event.request)
      .then(res => {
        if (res.ok) caches.open(CACHE_PAGES).then(c => c.put(event.request, res.clone()));
        return res;
      })
      .catch(() =>
        caches.match(event.request).then(cached => cached || new Response(
          `<!DOCTYPE html><html lang="es">
          <head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1">
          <title>Sin conexión — NovaEventos</title>
          <style>
            body{font-family:Arial,sans-serif;text-align:center;padding:60px 20px;background:#2a2929;color:#f0e9e3;}
            h1{color:#D4AF37;font-size:2rem;margin-bottom:10px;}
            p{color:#c9a898;margin:8px 0;}
            a{display:inline-block;margin-top:20px;background:#D4AF37;color:#2a2929;
              padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:700;}
          </style></head>
          <body>
            <h1>📡 Sin conexión</h1>
            <p>No hay internet en este momento.</p>
            <p>Revisa tu conexión e intenta de nuevo.</p>
            <a href="/">Reintentar</a>
          </body></html>`,
          { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
        ))
      )
  );
});

// ---- Notificaciones Push ----
self.addEventListener('push', event => {
  const data    = event.data ? event.data.json() : {};
  const title   = data.title || 'NovaEventos';
  const options = {
    body:    data.body  || 'Tienes una nueva notificación.',
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

// ---- Clic en notificación ----
self.addEventListener('notificationclick', event => {
  event.notification.close();
  if (event.action === 'dismiss') return;
  const url = event.notification.data?.url || '/';
  event.waitUntil(
    clients.matchAll({ type: 'window', includeUncontrolled: true }).then(list => {
      for (const c of list) {
        if (c.url.includes(url) && 'focus' in c) return c.focus();
      }
      if (clients.openWindow) return clients.openWindow(url);
    })
  );
});
