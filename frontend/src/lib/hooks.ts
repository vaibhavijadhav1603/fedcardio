"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";

export function useApi<T>(path: string | null, opts: { poll?: number } = {}) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(!!path);
  const alive = useRef(true);

  const load = useCallback(
    async (quiet = false) => {
      if (!path) return;
      if (!quiet) setLoading(true);
      try {
        const d = await api<T>(path);
        if (alive.current) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (alive.current) setError(e);
      } finally {
        if (alive.current) setLoading(false);
      }
    },
    [path],
  );

  useEffect(() => {
    alive.current = true;
    load();
    return () => {
      alive.current = false;
    };
  }, [load]);

  useEffect(() => {
    if (!opts.poll || !path) return;
    const t = setInterval(() => load(true), opts.poll);
    return () => clearInterval(t);
  }, [opts.poll, path, load]);

  return { data, error, loading, reload: load, setData };
}
