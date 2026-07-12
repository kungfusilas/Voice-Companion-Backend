/**
 * BondAI Service Worker — handles push notifications and offline caching.
 */

const CACHE_NAME = "bondai-v2";
const OFFLINE_URLS = ["/", "/manifest.webmanifest"];

// ── Install: pre-cache shell ──────────────────────────────────────────────────
self.addEventListener("install", (event) => {
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => cache.addAll(OFFLINE_URLS))
  );
  self.skipWaiting();
});

// ── Activate: clean up old caches ────────────────────────────────────────────
self.addEventListener("activate", (event) => {
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys.filter((k) => k !== CACHE_NAME).map((k) => caches.delete(k))
        )
      )
  );
  self.clients.claim();
});

// ── Push: display notification ────────────────────────────────────────────────
self.addEventListener("push", (event) => {
  let payload = { title: "BondAI", body: "You have a new message.", icon: "/icon-192.png", badge: "/favicon-32.png", data: {} };

  if (event.data) {
    try {
      payload = { ...payload, ...JSON.parse(event.data.text()) };
    } catch (_) {
      payload.body = event.data.text();
    }
  }

  const options = {
    body: payload.body,
    icon: payload.icon,
    badge: payload.badge,
    data: payload.data,
    vibrate: [100, 50, 100],
    requireInteraction: false,
  };

  event.waitUntil(self.registration.showNotification(payload.title, options));
});

// ── Notification click: focus or open app ────────────────────────────────────
self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  const targetUrl = event.notification.data?.url || "/";

  event.waitUntil(
    clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((windowClients) => {
        for (const client of windowClients) {
          if (client.url === targetUrl && "focus" in client) {
            return client.focus();
          }
        }
        if (clients.openWindow) {
          return clients.openWindow(targetUrl);
        }
      })
  );
});
