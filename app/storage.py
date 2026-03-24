from __future__ import annotations

import json
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)


class ModelStore(Generic[T]):
    def __init__(self, namespace: str, model_cls: type[T]) -> None:
        self.namespace = namespace
        self.model_cls = model_cls
        self._backend = self._build_backend()

    def _build_backend(self) -> "_StoreBackend[T]":
        if settings.state_backend == "postgres":
            return PostgresStore(self.namespace, self.model_cls)
        return JsonStore(self.namespace, self.model_cls)

    def get(self, item_id: str) -> T | None:
        return self._backend.get(item_id)

    def upsert(self, item_id: str, item: T) -> T:
        return self._backend.upsert(item_id, item)

    def delete(self, item_id: str) -> None:
        self._backend.delete(item_id)

    def list_all(self) -> list[T]:
        return self._backend.list_all()


class _StoreBackend(Generic[T]):
    def __init__(self, namespace: str, model_cls: type[T]) -> None:
        self.namespace = namespace
        self.model_cls = model_cls

    def get(self, item_id: str) -> T | None:
        raise NotImplementedError

    def upsert(self, item_id: str, item: T) -> T:
        raise NotImplementedError

    def delete(self, item_id: str) -> None:
        raise NotImplementedError

    def list_all(self) -> list[T]:
        raise NotImplementedError


class JsonStore(_StoreBackend[T]):
    def __init__(self, namespace: str, model_cls: type[T]) -> None:
        super().__init__(namespace, model_cls)
        self.path = Path(settings.data_dir) / f"{namespace}.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def _read_all(self) -> dict[str, dict]:
        raw = self.path.read_text(encoding="utf-8").strip()
        if not raw:
            return {}
        return json.loads(raw)

    def _write_all(self, payload: dict[str, dict]) -> None:
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")

    def get(self, item_id: str) -> T | None:
        payload = self._read_all()
        item = payload.get(item_id)
        return self.model_cls.model_validate(item) if item else None

    def upsert(self, item_id: str, item: T) -> T:
        payload = self._read_all()
        payload[item_id] = item.model_dump(mode="json")
        self._write_all(payload)
        return item

    def delete(self, item_id: str) -> None:
        payload = self._read_all()
        if item_id in payload:
            del payload[item_id]
            self._write_all(payload)

    def list_all(self) -> list[T]:
        payload = self._read_all()
        return [self.model_cls.model_validate(item) for item in payload.values()]


class PostgresStore(_StoreBackend[T]):
    def __init__(self, namespace: str, model_cls: type[T]) -> None:
        super().__init__(namespace, model_cls)
        if not settings.database_url:
            raise RuntimeError("STATE_BACKEND=postgres requires DATABASE_URL.")
        try:
            import psycopg  # type: ignore
        except ImportError as exc:
            raise RuntimeError("STATE_BACKEND=postgres requires psycopg to be installed.") from exc
        self._psycopg = psycopg
        self._ensure_schema()

    def _connect(self):
        return self._psycopg.connect(settings.database_url, autocommit=True)

    def _ensure_schema(self) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS state_store (
                    namespace TEXT NOT NULL,
                    item_id TEXT NOT NULL,
                    payload JSONB NOT NULL,
                    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                    PRIMARY KEY (namespace, item_id)
                )
                """
            )

    def get(self, item_id: str) -> T | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM state_store WHERE namespace = %s AND item_id = %s",
                (self.namespace, item_id),
            )
            row = cur.fetchone()
        return self.model_cls.model_validate(row[0]) if row else None

    def upsert(self, item_id: str, item: T) -> T:
        payload = json.dumps(item.model_dump(mode="json"))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO state_store(namespace, item_id, payload, updated_at)
                VALUES (%s, %s, %s::jsonb, NOW())
                ON CONFLICT (namespace, item_id)
                DO UPDATE SET payload = EXCLUDED.payload, updated_at = NOW()
                """,
                (self.namespace, item_id, payload),
            )
        return item

    def delete(self, item_id: str) -> None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "DELETE FROM state_store WHERE namespace = %s AND item_id = %s",
                (self.namespace, item_id),
            )

    def list_all(self) -> list[T]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT payload FROM state_store WHERE namespace = %s ORDER BY updated_at DESC",
                (self.namespace,),
            )
            rows = cur.fetchall()
        return [self.model_cls.model_validate(row[0]) for row in rows]
