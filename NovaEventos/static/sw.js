/**
 * Service Worker — NovaEventos PWA
 * Estrategia: Cache First para assets estáticos, Network First para páginas dinámicas.
 */

const CACHE_NAME = 'novaeventos-v1';
const CACHE_STATIC = 'novaeventos-static-v1';

// Recursos que se cachean al instalar (shell de la app)
const URLS_PRECACHE = [
  '/',
  '/salones/',
  '/static/styles/bootstrap-4.1.2/bootstrap.min.css',
  '/static/plugins/font-awesome-4.7.0/css/font-awesome.min.css',
  '/static/styles/main_styles.css',
  '/static/styles/responsive.css',
  '/static/js/jquery-3.2.1.min.js',
  '/static/styles/bootstrap-4.1.2/bootstrap.min.js',
  '/static/images/icon-192x192.png',
  '/static/images/icon-512x512.png',
  '/static/manifest.json',
];

// ---- Instalación: pre-cachear el shell ----
self.addEventListener('install', event => {
  event.waitUntil(
    caches.open(CACHE_STATIC).then(cache => {
      console.log('[SW] Pre-cacheando recursos estáticos...');
      return cache.addAll(URLS_PRECACHE.map(url => new Request(url, { cache: 'reload' })));
    }).then(() => self.skipWaiting())
  );
});

// ---- Activación: limpiar caches viejos ----
self.addEventListener('activate', event => {
  event.waitUntil(
    caches.keys().then(keys =>
      Promise.all(
        keys
          .filter(k => k !== CACHE_NAME && k !== CACHE_STATIC)
          .map(k => {
            console.log('[SW] Eliminando cache viejo:', k);
            return caches.delete(k);
          })
      )
    ).then(() => self.clients.claim())
  );
});

// ---- Fetch: estrategia mixta ----
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);

  // Solo interceptar requests del mismo origen
  if (url.origin !== location.origin) return;

  // Excluir rutas de admin, API y media
  if (url.pathname.startsWith('/admin/') ||
      url.pathname.startsWith('/media/') ||
      url.pathname.startsWith('/calendario/json/') ||
      url.pathname.startsWith('/calendario/disponibilidad/')) {
    return;
  }

  // Assets estáticos → Cache First
  if (url.pathname.startsWith('/static/')) {
    event.respondWith(
      caches.match(event.request).then(cached => {
        if (cached) return cached;
        return fetch(event.request).then(response => {
          if (response.ok) {
            const clone = response.clone();
            caches.open(CACHE_STATIC).then(cache => cache.put(event.request, clone));
          }
          return response;
        });
      })
    );
    return;
  }

  // Páginas HTML → Network First con fallback offline
  event.respondWith(
    fetch(event.request)
      .then(response => {
        if (response.ok) {
          const clone = response.clone();
          caches.open(CACHE_NAME).then(cache => cache.put(event.request, clone));
        }
        return response;
      })
      .catch(() => {
        return caches.match(event.request).then(cached => {
          if (cached) return cached;
          // Página offline genérica
          return caches.match('/').then(home => home || new Response(
            `<!DOCTYPE html><html lang="es"><head><meta charset="UTF-8">
             <meta name="viewport" content="width=device-width, initial-scale=1">
             <title>Sin conexión — NovaEventos</title>
             <style>
               body { font-family: Arial, sans-serif; text-align: center; padding: 60px 20px; background: #2a2929; color: #f0e9e3; }
               h1 { color: #D4AF37; font-size: 2rem; }
               p { color: #c9a898; }
               a { color: #D4AF37; }
             </style></head>
             <body>
               <h1>📡 Sin conexión</h1>
               <p>No hay conexión a internet en este momento.</p>
               <p>Algunas secciones pueden no estar disponibles.</p>
               <a href="/">Intentar de nuevo</a>
             </body></html>`,
            { headers: { 'Content-Type': 'text/html; charset=utf-8' } }
          ));
        });
      })
  );
});
