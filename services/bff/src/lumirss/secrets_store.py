"""Server-side secret store (0018).

Secrets that the operator manages through the Lumi UI (RSSHub route
credentials, the WebDAV password) live OUTSIDE lumi.sqlite in a separate
JSON file with ``chmod 600``. This keeps the full backup of lumi.sqlite
free of secrets by construction, matching AD-0018-6.

Design constraints:

- values are write-only from the API's perspective: the store itself can
  read them back internally (the BFF needs them to talk to WebDAV), but
  no endpoint ever echoes them;
- writes are atomic (temp file + ``os.replace``) and always restore 0600
  permissions;
- a missing file means "nothing configured"; a corrupt file raises
  SecretsStoreError (surfaced honestly, never silently dropped).
"""

import json
import os
import tempfile
from pathlib import Path


class SecretsStoreError(Exception):
    """The secret store file exists but cannot be read (corruption)."""


class SecretsStore:
    """Small JSON-file secret store (single file, 0600)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    @property
    def path(self) -> Path:
        return self._path

    def _load(self) -> dict[str, str]:
        if not self._path.exists():
            return {}
        try:
            raw = self._path.read_text(encoding="utf-8")
        except OSError as exc:
            raise SecretsStoreError("Could not read the secret store.") from exc
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise SecretsStoreError("The secret store is corrupt.") from exc
        if not isinstance(parsed, dict) or any(
            not isinstance(k, str) or not isinstance(v, str)
            for k, v in parsed.items()
        ):
            raise SecretsStoreError("The secret store has an invalid shape.")
        return parsed

    def _save(self, values: dict[str, str]) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise SecretsStoreError("Could not create the secret store directory.") from exc
        fd, tmp_name = tempfile.mkstemp(
            prefix=".secrets-", dir=str(self._path.parent)
        )
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(values, handle, ensure_ascii=False, sort_keys=True)
                handle.write("\n")
            os.replace(tmp_name, self._path)
        except OSError as exc:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise SecretsStoreError("Could not write the secret store.") from exc
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass

    def get(self, key: str) -> str | None:
        """Read one secret value (BFF-internal use only, never echoed)."""
        return self._load().get(key)

    def configured(self, key: str) -> bool:
        """Whether a non-empty value is stored for ``key``."""
        value = self._load().get(key)
        return value is not None and value.strip() != ""

    def configured_map(self, keys: list[str]) -> dict[str, bool]:
        """Configured flags for many keys (single read)."""
        values = self._load()
        return {
            key: values.get(key) is not None and values.get(key, "").strip() != ""
            for key in keys
        }

    def set(self, key: str, value: str) -> None:
        """Store a non-empty secret value."""
        if not value.strip():
            raise ValueError("secret value must not be blank")
        values = self._load()
        values[key] = value
        self._save(values)

    def delete(self, key: str) -> bool:
        """Remove a secret; True when it existed."""
        values = self._load()
        if key not in values:
            return False
        del values[key]
        self._save(values)
        return True
