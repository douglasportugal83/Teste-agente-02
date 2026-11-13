"use client";

import { useEffect, useState } from "react";
import { API_URL, getToken } from "@/lib/api";

export type LiveStatus = "connecting" | "online" | "offline";

/** Mantém o WebSocket de status aberto, reconectando com backoff exponencial. */
export function useLiveStatus(): LiveStatus {
  const [status, setStatus] = useState<LiveStatus>("connecting");

  useEffect(() => {
    let socket: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let attempt = 0;
    let closed = false;

    const connect = () => {
      const token = getToken();
      if (closed || !token) return;
      socket = new WebSocket(`${API_URL.replace(/^http/, "ws")}/ws/status`);
      // O token vai na primeira mensagem, não na URL, para não aparecer em logs.
      socket.onopen = () => socket?.send(JSON.stringify({ type: "auth", token }));
      socket.onmessage = () => {
        attempt = 0;
        setStatus("online");
      };
      socket.onclose = () => {
        if (closed) return;
        setStatus("offline");
        timer = setTimeout(connect, Math.min(30_000, 1_000 * 2 ** attempt++));
      };
    };
    connect();

    return () => {
      closed = true;
      clearTimeout(timer);
      socket?.close();
    };
  }, []);

  return status;
}
