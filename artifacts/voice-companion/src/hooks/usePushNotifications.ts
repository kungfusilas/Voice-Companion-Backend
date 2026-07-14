/**
 * usePushNotifications — registers the service worker, requests permission,
 * and subscribes the browser to Web Push.
 *
 * Usage:
 *   const { supported, permission, subscribed, subscribe, unsubscribe } = usePushNotifications();
 */
import { useState, useEffect, useCallback } from "react";

const SW_PATH = "/sw.js";
const API_BASE = "/companion/api/push";

function urlBase64ToUint8Array(base64String: string): Uint8Array {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}

async function fetchVapidKey(): Promise<string> {
  const res = await fetch(`${API_BASE}/vapid-public-key`);
  if (!res.ok) throw new Error("Failed to fetch VAPID key");
  const { publicKey } = await res.json();
  return publicKey;
}

async function getRegistration(): Promise<ServiceWorkerRegistration> {
  const existing = await navigator.serviceWorker.getRegistration(SW_PATH);
  if (existing) return existing;
  return navigator.serviceWorker.register(SW_PATH, { scope: "/" });
}

export interface UsePushNotificationsResult {
  supported: boolean;
  permission: NotificationPermission | "unsupported";
  subscribed: boolean;
  loading: boolean;
  subscribe: (authToken: string) => Promise<boolean>;
  unsubscribe: (authToken: string) => Promise<boolean>;
}

export function usePushNotifications(): UsePushNotificationsResult {
  const supported =
    typeof window !== "undefined" &&
    "serviceWorker" in navigator &&
    "PushManager" in window &&
    "Notification" in window;

  const [permission, setPermission] = useState<NotificationPermission | "unsupported">(
    supported ? Notification.permission : "unsupported"
  );
  const [subscribed, setSubscribed] = useState(false);
  const [loading, setLoading] = useState(false);

  // Check if already subscribed on mount
  useEffect(() => {
    if (!supported) return;
    (async () => {
      try {
        const reg = await navigator.serviceWorker.getRegistration(SW_PATH);
        if (!reg) return;
        const sub = await reg.pushManager.getSubscription();
        setSubscribed(!!sub);
      } catch (_) {
        // ignore
      }
    })();
  }, [supported]);

  const subscribe = useCallback(
    async (authToken: string): Promise<boolean> => {
      if (!supported) return false;
      setLoading(true);
      try {
        const perm = await Notification.requestPermission();
        setPermission(perm);
        if (perm !== "granted") return false;

        const [reg, vapidKey] = await Promise.all([getRegistration(), fetchVapidKey()]);

        const sub = await reg.pushManager.subscribe({
          userVisibleOnly: true,
          // Cast: newer TS types Uint8Array as Uint8Array<ArrayBufferLike>, but the
          // DOM's applicationServerKey expects a BufferSource (ArrayBufferView<ArrayBuffer>).
          applicationServerKey: urlBase64ToUint8Array(vapidKey) as BufferSource,
        });

        const json = sub.toJSON() as {
          endpoint: string;
          keys: { p256dh: string; auth: string };
        };

        const res = await fetch(`${API_BASE}/subscribe`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify({
          ...json,
          timezone_offset_hours: Math.round(new Date().getTimezoneOffset() / -60),
        }),
        });

        if (!res.ok) throw new Error("Subscription save failed");
        setSubscribed(true);
        return true;
      } catch (err) {
        console.error("[push] subscribe error", err);
        return false;
      } finally {
        setLoading(false);
      }
    },
    [supported]
  );

  const unsubscribe = useCallback(
    async (authToken: string): Promise<boolean> => {
      if (!supported) return false;
      setLoading(true);
      try {
        const reg = await navigator.serviceWorker.getRegistration(SW_PATH);
        if (!reg) return false;
        const sub = await reg.pushManager.getSubscription();
        if (!sub) return false;

        const json = sub.toJSON() as {
          endpoint: string;
          keys: { p256dh: string; auth: string };
        };

        await sub.unsubscribe();

        await fetch(`${API_BASE}/unsubscribe`, {
          method: "DELETE",
          headers: {
            "Content-Type": "application/json",
            Authorization: `Bearer ${authToken}`,
          },
          body: JSON.stringify(json),
        });

        setSubscribed(false);
        return true;
      } catch (err) {
        console.error("[push] unsubscribe error", err);
        return false;
      } finally {
        setLoading(false);
      }
    },
    [supported]
  );

  return { supported, permission, subscribed, loading, subscribe, unsubscribe };
}
