"""Cliente PocketBase usando o SDK oficial — autentica como superuser."""
from __future__ import annotations

from pocketbase import PocketBase


class PocketBaseClient:
    def __init__(self, url: str, email: str, password: str):
        self.url = url.rstrip("/")
        self.email = email
        self.password = password
        self._client: PocketBase | None = None

    def _get_client(self) -> PocketBase:
        if self._client is None:
            self._client = PocketBase(self.url)
        return self._client

    def authenticate(self) -> str:
        """Autentica como superuser (_superusers) e retorna o token."""
        client = self._get_client()
        result = client.collection("_superusers").auth_with_password(
            self.email, self.password
        )
        return result.token

    def fetch_records(
        self,
        collection: str,
        filter_expr: str = "",
        sort: str = "",
        page: int = 1,
        per_page: int = 50,
    ) -> list[dict]:
        """Busca registros de uma collection. Autentica automaticamente se necessário."""
        client = self._get_client()
        if not client.auth_store.token:
            self.authenticate()

        query_params: dict = {}
        if filter_expr:
            query_params["filter"] = filter_expr
        if sort:
            query_params["sort"] = sort

        result = client.collection(collection).get_list(
            page=page, per_page=per_page, query_params=query_params or None
        )
        return [item.__dict__ for item in result.items]

    def get_collection_fields(self, collection: str) -> list[str]:
        """Retorna os nomes dos campos da collection (baseado no primeiro registro)."""
        records = self.fetch_records(collection, per_page=1)
        if records:
            return list(records[0].keys())
        return []


# ── Instância compartilhada (singleton) ──────────────────────────────────────

_shared: PocketBaseClient | None = None


def get_shared() -> PocketBaseClient | None:
    """Retorna a instância compartilhada (None se ainda não inicializada)."""
    return _shared


def init_shared(url: str, email: str, password: str) -> PocketBaseClient:
    """Cria (ou recria) a instância compartilhada com as credenciais fornecidas."""
    global _shared
    _shared = PocketBaseClient(url, email, password)
    return _shared
