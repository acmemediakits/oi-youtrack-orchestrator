from __future__ import annotations

import json
from pathlib import Path
from typing import Generic, TypeVar

from pydantic import BaseModel

from app.config import settings

T = TypeVar("T", bound=BaseModel)


class JsonStore(Generic[T]):
    def __init__(self, filename: str, model_cls: type[T]) -> None:
        self.path = Path(settings.data_dir) / filename
        self.model_cls = model_cls
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
