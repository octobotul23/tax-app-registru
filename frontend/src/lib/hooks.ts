/**
 * Small data-loading hooks.
 *
 * Deliberately not a data-fetching library. This app has about a dozen
 * endpoints and two users; `useAsync` plus a manual `reload()` is less code
 * than configuring a cache, and it makes the refresh points explicit - which
 * matters here, because a queued receipt changes status behind the user's back
 * and the list has to notice.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { ApiError } from "../api/client";

export interface AsyncState<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  reload: () => void;
  setData: (value: T) => void;
}

export function useAsync<T>(
  loader: () => Promise<T>,
  deps: readonly unknown[] = [],
): AsyncState<T> {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);

  // Guards against a slow first request resolving after a faster second one
  // and overwriting newer data with older data.
  const requestId = useRef(0);

  useEffect(() => {
    const id = ++requestId.current;
    let cancelled = false;

    setLoading(true);
    loader()
      .then((result) => {
        if (cancelled || id !== requestId.current) return;
        setData(result);
        setError(null);
      })
      .catch((cause: unknown) => {
        if (cancelled || id !== requestId.current) return;
        setError(cause instanceof ApiError ? cause.message : String(cause));
      })
      .finally(() => {
        if (!cancelled && id === requestId.current) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);

  const reload = useCallback(() => setNonce((n) => n + 1), []);

  return { data, error, loading, reload, setData };
}

/**
 * Re-run `callback` on an interval, but only while the tab is visible.
 *
 * Used to watch documents that are still being scanned. Polling a hidden tab
 * would keep a phone's radio awake for a list nobody is looking at.
 */
export function usePolling(callback: () => void, intervalMs: number, enabled: boolean): void {
  const saved = useRef(callback);
  saved.current = callback;

  useEffect(() => {
    if (!enabled || intervalMs <= 0) return;

    let timer: number | undefined;

    const start = () => {
      stop();
      timer = window.setInterval(() => saved.current(), intervalMs);
    };
    const stop = () => {
      if (timer !== undefined) window.clearInterval(timer);
      timer = undefined;
    };
    const onVisibility = () => {
      if (document.visibilityState === "visible") {
        saved.current();
        start();
      } else {
        stop();
      }
    };

    if (document.visibilityState === "visible") start();
    document.addEventListener("visibilitychange", onVisibility);

    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [intervalMs, enabled]);
}

/** A value that persists in localStorage, for per-device preferences. */
export function useStoredState<T>(
  key: string,
  initial: T,
): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      const stored = window.localStorage.getItem(key);
      return stored === null ? initial : (JSON.parse(stored) as T);
    } catch {
      // Private browsing, or site data blocked. The default is fine.
      return initial;
    }
  });

  const update = useCallback(
    (next: T) => {
      setValue(next);
      try {
        window.localStorage.setItem(key, JSON.stringify(next));
      } catch {
        // Not being able to remember a filter choice is not worth an error.
      }
    },
    [key],
  );

  return [value, update];
}
