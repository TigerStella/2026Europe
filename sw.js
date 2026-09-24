/* 노을과 타이거의 유럽여행 — service worker (오프라인 지원) */
// 배포마다 버전을 올린다 → 이전 앱 셸 캐시는 activate 때 정리됨
const CACHE = 'noleu-europe-v67';
// 🎧 도슨트 음성 오프라인 저장본(박물관 화면의 「📥 오프라인 저장」 버튼이 채움) — 버전업 때 지우지 않음
const KEEP_PREFIX = 'trapble-history-audio';
const ASSETS = [
  './', './manifest.webmanifest', './bag-192.png', './bag-512.png',
  './data/docent_paris_orsay_orangerie.json', './audio/manifest.json',
];

self.addEventListener('install', (e) => {
  e.waitUntil(
    caches.open(CACHE).then((c) => c.addAll(ASSETS)).then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (e) => {
  e.waitUntil(
    caches.keys()
      .then((ks) => Promise.all(ks.filter((k) => k !== CACHE && !k.startsWith(KEEP_PREFIX)).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (e) => {
  const req = e.request;
  if (req.method !== 'GET') return;
  const url = new URL(req.url);

  // 페이지 이동: 네트워크 우선(온라인=항상 최신) + 4초 내 응답 없거나 오프라인이면 저장본
  if (req.mode === 'navigate') {
    e.respondWith((async () => {
      try {
        const res = await Promise.race([
          fetch(req),
          new Promise((_, rej) => setTimeout(() => rej(new Error('timeout')), 4000)),
        ]);
        if (res && res.status === 200) { const cp = res.clone(); (await caches.open(CACHE)).put('./', cp); }
        return res;
      } catch (err) {
        const cached = await caches.match('./');
        return cached || fetch(req);
      }
    })());
    return;
  }

  // 도슨트 데이터(JSON)·음성 목록: 네트워크 우선(내용 갱신 반영) → 오프라인이면 저장본
  if (url.origin === location.origin && (url.pathname.includes('/data/') || url.pathname.endsWith('/audio/manifest.json'))) {
    e.respondWith((async () => {
      try {
        const res = await fetch(req);
        if (res && res.status === 200) { const cp = res.clone(); (await caches.open(CACHE)).put(req, cp); }
        return res;
      } catch (err) {
        const cached = await caches.match(req, { ignoreSearch: true });
        if (cached) return cached;
        throw err;
      }
    })());
    return;
  }

  // 같은 출처(앱 자산): 캐시 우선, 없으면 네트워크 후 캐시 (오프라인 저장한 음성도 여기서 찾아짐)
  if (url.origin === location.origin) {
    e.respondWith(
      caches.match(req).then((cached) => cached || fetch(req).then((res) => {
        if (res && res.status === 200) { const cp = res.clone(); caches.open(CACHE).then((c) => c.put(req, cp)); }
        return res;
      }))
    );
    return;
  }

  // 외부(환율·날씨·도서 API·썸네일): SW가 개입하지 않고 브라우저가 직접 처리
  // (서비스워커 재요청이 일부 CORS 요청을 깨뜨리는 문제 방지)
});
