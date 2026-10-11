from __future__ import annotations

import hashlib
import pickle
from pathlib import Path
from typing import Any


class DiskCache:
    def __init__(
        self,
        directory: str | Path,
        *,
        namespace: str = "generic",
        version: str = "v1",
    ):
        self.base_directory = Path(directory)
        self.namespace = namespace
        self.version = version
        self.directory = self.base_directory / namespace / version
        self.directory.mkdir(parents=True, exist_ok=True)

    def path_for(self, key: str, suffix: str = ".pickle") -> Path:
        safe = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.directory / f"{safe}{suffix}"

    def get(self, key: str) -> Any | None:
        path = self.path_for(key)
        if not path.exists():
            return None
        try:
            with path.open("rb") as stream:
                return pickle.load(stream)
        except (pickle.PickleError, EOFError, AttributeError, ImportError, TypeError):
            # Cache data is disposable. It can become incompatible after a
            # Streamlit hot reload or an application upgrade, so recover as a
            # cache miss instead of aborting the user's PDF job.
            path.unlink(missing_ok=True)
            return None

    def set(self, key: str, value: Any) -> bool:
        path = self.path_for(key)
        temporary = path.with_suffix(".tmp")
        try:
            with temporary.open("wb") as stream:
                pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
            temporary.replace(path)
            return True
        except (pickle.PickleError, AttributeError, TypeError):
            temporary.unlink(missing_ok=True)
            return False

    def delete(self, key: str) -> bool:
        path = self.path_for(key)
        if not path.exists():
            return False
        path.unlink()
        return True

    def clear(self) -> int:
        removed = 0
        for path in self.directory.glob("*"):
            if path.is_file():
                path.unlink()
                removed += 1
        return removed

