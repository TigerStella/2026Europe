/* 노을과 타이거의 유럽여행 — service worker (오프라인 지원) */
const CACHE = 'noleu-europe-v2';
const ASSETS = ['./', './manifest.webmanifest', './icon-192.png', './icon-512.png'];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // 페이지 이동: 캐시 우선(오프라인 즉시 실행) + 백그라운드로 최신본 갱신
  if (req.mode === 'navigate') {
    e.respondWith(
      caches.match('./').then((cached) => {
        const net = fetch(req).then((res) => {
          if (res && res.status === 200) { const cp = res.clone(); caches.open(CACHE).then((c) => c.put('./', cp)); }
          return res;
        }).catch(() => cached);
        return cached || net;
      })
    );
    return;
  }

  // 같은 출처(앱 자산): 캐시 우선, 없으면 네트워크 후 캐시
  if (url.origin === location.origin) {
    e.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        if (res && res.status === 200) { const cp = res.clone(); caches.open(CACHE).then((c) => c.put(req, cp)); }
        return res;
      }))
    );
    return;
  }

  // 외부(환율·날씨·도서 API·폰트·썸네일): 네트워크 → 실패 시 캐시
  e.respondWith(fetch(req).catch(() => caches.match(req)));
});
