const CACHE_NAME = 'openclaw-observatory-v2';
const OFFLINE_URL = '/static/offline.html';
const CORE_ASSETS = [
  '/',
  '/static/manifest.webmanifest',
  '/static/favicon.svg',
  '/static/vendor/socket.io/socket.io.min.js',
  '/static/vendor/marked/marked.min.js',
  '/static/vendor/dompurify/purify.min.js',
  '/static/vendor/highlightjs/highlight.min.js',
  '/static/vendor/highlightjs/github-dark.min.css',
  OFFLINE_URL,
];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(CORE_ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key !== CACHE_NAME).map((key) => caches.delete(key))
    )).then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  if (event.request.method !== 'GET') return;
  const url = new URL(event.request.url);

  const isApiRequest =
    url.pathname.startsWith('/docs/') ||
    url.pathname.startsWith('/insights') ||
    url.pathname.startsWith('/ready') ||
    url.pathname.startsWith('/capabilities') ||
    url.pathname.startsWith('/drilldown/');

  if (isApiRequest) {
    event.respondWith(
      fetch(event.request).catch(() => {
        const contentType = event.request.headers.get('accept') || '';
        if (contentType.includes('application/json')) {
          return new Response(JSON.stringify({ ok: false, error: 'offline' }), {
            status: 503,
            headers: { 'Content-Type': 'application/json' },
          });
        }
        return new Response('Service unavailable', { status: 503, headers: { 'Content-Type': 'text/plain' } });
      })
    );
    return;
  }

  if (event.request.mode === 'navigate') {
    event.respondWith(
      fetch(event.request)
        .then((response) => {
          const copy = response.clone();
          caches.open(CACHE_NAME).then((cache) => cache.put('/', copy));
          return response;
        })
        .catch(async () => {
          const cache = await caches.open(CACHE_NAME);
          return (await cache.match('/')) || (await cache.match(OFFLINE_URL));
        })
    );
    return;
  }

  if (url.origin === self.location.origin) {
    event.respondWith(
      caches.match(event.request).then((cached) => {
        if (cached) return cached;
        return fetch(event.request)
          .then((response) => {
            if (!response || response.status !== 200 || response.type !== 'basic') return response;
            const copy = response.clone();
            caches.open(CACHE_NAME).then((cache) => cache.put(event.request, copy));
            return response;
          })
          .catch(() => caches.match(OFFLINE_URL));
      })
    );
  }
});
