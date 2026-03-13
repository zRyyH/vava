"""Servidor WebSocket para comunicação com clientes Win Control."""
from __future__ import annotations

import asyncio
import json
import threading

import websockets
from PySide6.QtCore import QObject, Signal


class ClientInfo:
    def __init__(self, client_id: str, ws):
        self.id = client_id
        self.ws = ws


class WinControlServer(QObject):
    client_connected    = Signal(str)       # client_id
    client_disconnected = Signal(str)       # client_id
    response_received   = Signal(str, dict) # client_id, msg
    status_changed      = Signal(str)

    def __init__(self):
        super().__init__()
        self._clients: dict[str, ClientInfo] = {}
        self._loop: asyncio.AbstractEventLoop | None = None
        self._next_id = 1
        self._thread: threading.Thread | None = None

    def start(self, host: str = "0.0.0.0", port: int = 8765):
        self._thread = threading.Thread(
            target=self._run, args=(host, port), daemon=True
        )
        self._thread.start()

    def send_command(self, client_id: str, action: str, params: dict | None = None) -> int | None:
        client = self._clients.get(client_id)
        if not client or not self._loop:
            return None
        rid = self._next_id
        self._next_id += 1
        msg: dict = {"id": rid, "action": action}
        if params:
            for k, v in params.items():
                # "action" dentro de window_action é enviado como "wa" para evitar conflito
                msg["wa" if k == "action" else k] = v
        asyncio.run_coroutine_threadsafe(
            client.ws.send(json.dumps(msg)), self._loop
        )
        return rid

    def get_client_ids(self) -> list[str]:
        return list(self._clients.keys())

    def is_connected(self, client_id: str) -> bool:
        return client_id in self._clients

    # ── internals ─────────────────────────────────────────────────────────────

    def _run(self, host: str, port: int):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve(host, port))

    async def _serve(self, host: str, port: int):
        server = await websockets.serve(
            self._handler, host, port, max_size=10 * 1024 * 1024
        )
        self.status_changed.emit(f"Servidor ouvindo em {host}:{port}")
        await server.wait_closed()

    async def _handler(self, ws):
        remote = ws.remote_address
        client_id = f"{remote[0]}:{remote[1]}"
        self._clients[client_id] = ClientInfo(client_id, ws)
        self.client_connected.emit(client_id)
        self.status_changed.emit(f"Cliente conectado: {client_id}")
        try:
            async for raw in ws:
                self.response_received.emit(client_id, json.loads(raw))
        except Exception:
            pass
        finally:
            del self._clients[client_id]
            self.client_disconnected.emit(client_id)
            self.status_changed.emit(f"Cliente desconectado: {client_id}")
