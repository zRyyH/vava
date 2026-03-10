import asyncio
import json
import threading
from PySide6.QtCore import QObject, Signal


class ClientInfo:
    def __init__(self, client_id: str, ws):
        self.id = client_id
        self.ws = ws
        self.hostname = ""


class WinControlServer(QObject):
    client_connected = Signal(str)       # client_id
    client_disconnected = Signal(str)    # client_id
    response_received = Signal(str, dict)  # client_id, msg
    status_changed = Signal(str)

    def __init__(self):
        super().__init__()
        self._clients: dict[str, ClientInfo] = {}
        self._loop = None
        self._server = None
        self._next_id = 1
        self._thread = None

    def start(self, host="0.0.0.0", port=8765):
        self._thread = threading.Thread(
            target=self._run, args=(host, port), daemon=True
        )
        self._thread.start()

    def _run(self, host, port):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve(host, port))

    async def _serve(self, host, port):
        import websockets
        self._server = await websockets.serve(self._handler, host, port, max_size=10 * 1024 * 1024)
        self.status_changed.emit(f"Server listening on {host}:{port}")
        await self._server.wait_closed()

    async def _handler(self, ws):
        remote = ws.remote_address
        client_id = f"{remote[0]}:{remote[1]}"
        client = ClientInfo(client_id, ws)
        self._clients[client_id] = client
        self.client_connected.emit(client_id)
        self.status_changed.emit(f"Client connected: {client_id}")
        try:
            async for raw in ws:
                msg = json.loads(raw)
                self.response_received.emit(client_id, msg)
        except Exception:
            pass
        finally:
            del self._clients[client_id]
            self.client_disconnected.emit(client_id)
            self.status_changed.emit(f"Client disconnected: {client_id}")

    def send_command(self, client_id: str, action: str, **params) -> int | None:
        client = self._clients.get(client_id)
        if not client or not self._loop:
            return None
        rid = self._next_id
        self._next_id += 1
        msg = {"action": action, "id": rid, **params}
        asyncio.run_coroutine_threadsafe(
            client.ws.send(json.dumps(msg)), self._loop
        )
        return rid

    def get_client_ids(self) -> list[str]:
        return list(self._clients.keys())

    def is_connected(self, client_id: str) -> bool:
        return client_id in self._clients
