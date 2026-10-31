'use strict';

// Network first, so the app stays fresh and authentik can still redirect to
// its login page. The cache only steps in when the network is unreachable.
// API calls are never cached: they always need the live answer.
const CACHE = 'amble-v1';
const SHELL = [
  '/',
  '/style.css',
  '/app.js',
  '/favicon.svg',
  '/manifest.webmanifest',
  '/icons/icon-192.png',
  '/icons/apple-touch-icon.png',
];
const FONT_HOSTS = ['fonts.googleapis.com', 'fonts.gstatic.com'];

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      // A failed precache (e.g. signed out) shouldn't block installing.
      .then((cache) => Promise.allSettled(SHELL.map((url) => cacheIfFresh(cache, url))))
      .then(() => self.skipWaiting()),
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim()),
  );
});

self.addEventListener('fetch', (event) => {
  const { request } = event;
  if (request.method !== 'GET') return;
  const url = new URL(request.url);
  const sameOrigin = url.origin === self.location.origin;
  if (sameOrigin && (url.pathname.startsWith('/api/') || url.pathname === '/healthz')) return;
  if (!sameOrigin && !FONT_HOSTS.includes(url.hostname)) return;
  event.respondWith(networkFirst(request));
});

async function cacheIfFresh(cache, url) {
  const res = await fetch(url, { credentials: 'same-origin', redirect: 'manual' });
  if (res.ok && !res.redirected) await cache.put(url, res);
}

async function networkFirst(request) {
  const cache = await caches.open(CACHE);
  try {
    const res = await fetch(request);
    // Only keep real content, never a login redirect or error page.
    const cors = res.type === 'cors' || res.type === 'basic';
    if (res.ok && !res.redirected && cors) cache.put(request, res.clone());
    return res;
  } catch (err) {
    const cached = await cache.match(request, { ignoreSearch: request.mode === 'navigate' });
    if (cached) return cached;
    throw err;
  }
}
