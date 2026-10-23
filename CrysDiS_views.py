"""Versioned, atomic storage for named crystal display presets."""
from __future__ import annotations

import copy
import json
import os
import tempfile
import threading
import uuid
from pathlib import Path


_STORE_LOCK = threading.RLock()


class DisplayPresetStore:
    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @staticmethod
    def name(value: str) -> str:
        value = str(value or "").strip()
        if not value or len(value) > 120:
            raise ValueError("Use a saved-view name between 1 and 120 characters.")
        return value

    def read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise ValueError(f"Cannot read saved views: {exc}. The file has not been changed.") from exc
        try:
            if not isinstance(data, dict) or data["version"] != 1 or not isinstance(data["views"], list):
                raise ValueError("Unsupported saved-view format.")
            ids, names, defaults = set(), set(), set()
            for view in data["views"]:
                if not isinstance(view, dict):
                    raise ValueError("Invalid saved view.")
                for key in ("id", "crystal_id", "structure_version"):
                    if not isinstance(view[key], str) or not view[key]:
                        raise ValueError("Invalid saved-view identity.")
                pair = (view["crystal_id"], self.name(view["name"]).casefold())
                if view["id"] in ids or pair in names:
                    raise ValueError("Duplicate saved-view identity or name.")
                if not isinstance(view["payload"], dict) or type(view["default"]) is not bool:
                    raise ValueError("Invalid saved-view settings.")
                if view["default"]:
                    if view["crystal_id"] in defaults:
                        raise ValueError("More than one default view for a crystal.")
                    defaults.add(view["crystal_id"])
                ids.add(view["id"])
                names.add(pair)
            return data["views"]
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"Cannot read saved views: {exc}. The file has not been changed.") from exc

    def for_crystal(self, crystal_id: str) -> list[dict]:
        return [view for view in self.read() if view["crystal_id"] == crystal_id]

    def _write(self, views: list[dict]) -> None:
        # Serialize before touching the file; reject non-finite data rather than write invalid JSON.
        text = json.dumps({"version": 1, "views": views}, indent=2, ensure_ascii=True, allow_nan=False) + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             suffix=".tmp", delete=False) as handle:
                temporary = Path(handle.name)
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self, crystal_id: str, structure_version: str, name: str, payload: dict,
             *, view_id: str | None = None, default: bool = False) -> dict:
        name = self.name(name)
        with _STORE_LOCK:
            views = self.read()
            current = next((v for v in views if v["id"] == view_id), None)
            if view_id is not None and (current is None or current["crystal_id"] != crystal_id):
                raise ValueError("This saved view no longer exists for this crystal.")
            if any(v["crystal_id"] == crystal_id and v["name"].casefold() == name.casefold()
                   and v["id"] != view_id for v in views):
                raise ValueError("A view with this name already exists. Choose another name or update that view.")
            view = dict(id=view_id or str(uuid.uuid4()), crystal_id=crystal_id, structure_version=structure_version,
                        name=name, payload=copy.deepcopy(payload), default=bool(default))
            if default:
                for item in views:
                    if item["crystal_id"] == crystal_id:
                        item["default"] = False
            if current is None:
                views.append(view)
            else:
                views[views.index(current)] = view
            self._write(views)
            return copy.deepcopy(view)

    def change(self, view_id: str, action: str, value=None) -> None:
        with _STORE_LOCK:
            views = self.read()
            view = next((v for v in views if v["id"] == view_id), None)
            if view is None:
                raise ValueError("This saved view no longer exists.")
            if action == "delete":
                views.remove(view)
            elif action == "rename":
                name = self.name(value)
                if any(v is not view and v["crystal_id"] == view["crystal_id"]
                       and v["name"].casefold() == name.casefold() for v in views):
                    raise ValueError("A view with this name already exists.")
                view["name"] = name
            elif action == "default":
                for item in views:
                    if item["crystal_id"] == view["crystal_id"]:
                        item["default"] = item is view and bool(value)
            else:
                raise ValueError("Unknown saved-view action.")
            self._write(views)

    def delete_crystal(self, crystal_id: str) -> None:
        with _STORE_LOCK:
            views = self.read()
            remaining = [view for view in views if view["crystal_id"] != crystal_id]
            if len(remaining) != len(views):
                self._write(remaining)
