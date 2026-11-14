const SHELL_CACHE = 'karuvottam-shell-v2';
const SHELL_ASSETS = [
  '/static/offline.html',
  '/static/offline-lang.js',
  '/static/style.css',
  '/static/icons/icon-192.png',
  '/static/icons/icon-512.png'
];
const PUBLIC_PAGES = new Set(['/', '/calendar', '/prediction', '/observations', '/events', '/climate']);

self.addEventListener('install', (event) => {
  event.waitUntil(caches.open(SHELL_CACHE).then((cache) => cache.addAll(SHELL_ASSETS)));
  self.skipWaiting();
});

self.addEventListener('activate', (event) => {
  event.waitUntil(Promise.all([
    caches.keys().then((keys) => Promise.all(
      keys.filter((key) => key.startsWith('karuvottam-shell-') && key !== SHELL_CACHE)
        .map((key) => caches.delete(key))
    )),
    self.clients.claim()
  ]));
});

self.addEventListener('fetch', (event) => {
  const request = event.request;
  if (request.method !== 'GET' || request.mode !== 'navigate') return;
  const url = new URL(request.url);
  if (url.origin !== self.location.origin || !PUBLIC_PAGES.has(url.pathname)) return;
  event.respondWith(
    fetch(request, { cache: 'no-store' }).catch(() => caches.match('/static/offline.html'))
  );
});
