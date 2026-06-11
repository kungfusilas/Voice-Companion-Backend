/*
 * KILL-SWITCH SERVICE WORKER
 *
 * This app is online-only. A previous service worker cached the app shell
 * with content-hashed bundle filenames. After a rebuild those hashes change,
 * the cached shell references dead files, and the app shows a permanent white
 * screen on every load — especially on installed PWAs.
 *
 * This replacement SW does nothing except:
 *   1. Activate immediately (skipWaiting + clients.claim)
 *   2. Delete every cache entry
 *   3. Unregister itself
 *   4. Reload all controlled clients so they fetch the fresh app from the network
 *
 * Once this runs, there is no service worker left and the app loads normally.
 */

self.addEventListener("install", (event) => {
  // Activate right away — don't wait for old SW to finish.
  self.skipWaiting();
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      // Delete every cache this origin owns.
      const cacheNames = await caches.keys();
      await Promise.all(cacheNames.map((name) => caches.delete(name)));

      // Take control of all open tabs immediately.
      await clients.claim();

      // Unregister this SW — we don't want any SW registered going forward.
      await self.registration.unregister();

      // Reload every controlled client so they get the live network response.
      const allClients = await clients.matchAll({ type: "window", includeUncontrolled: true });
      for (const client of allClients) {
        client.navigate(client.url);
      }
    })()
  );
});
