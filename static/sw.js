// Service worker do Transkriptor: cacheia o "shell" (página + ícones) para o app
// abrir instalado/offline. As chamadas de API sempre vão para a rede.
const CACHE = 'transkriptor-v1';
const SHELL = [
  '/',
  '/manifest.webmanifest',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png',
  '/static/icons/apple-touch-icon.png',
];

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(CACHE).then((c) => c.addAll(SHELL)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys().then((keys) =>
      Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k)))
    )
  );
  self.clients.claim();
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // Página: rede primeiro (sempre a versão mais nova), cache como fallback offline.
  if (req.mode === 'navigate') {
    event.respondWith(
      fetch(req)
        .then((res) => {
          const copy = res.clone();
          caches.open(CACHE).then((c) => c.put('/', copy));
          return res;
        })
        .catch(() => caches.match('/'))
    );
    return;
  }

  // Arquivos estáticos do próprio site: cache primeiro.
  if (url.origin === self.location.origin && (url.pathname.startsWith('/static/') || url.pathname === '/manifest.webmanifest')) {
    event.respondWith(caches.match(req).then((hit) => hit || fetch(req)));
  }
  // Demais requisições (API, downloads, fontes externas): comportamento normal.
});
