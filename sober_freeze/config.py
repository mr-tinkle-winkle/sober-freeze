"""
Runtime settings, in ``$XDG_CONFIG_HOME/sober-freeze/config.toml``.  The CLI
(``sober-freeze auto-unfreeze ...``), the GUI and the background daemon all use this one file;
the daemon notices changes by the file's mtime, so a change applies within a second.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, fields
from pathlib import Path

MIN_SECONDS, MAX_SECONDS = 1, 3600


def config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "sober-freeze" / "config.toml"


@dataclass
class Config:
    auto_unfreeze: bool = True           # thaw anything frozen through sober-freeze after a while
    auto_unfreeze_seconds: int = 20      # ... this many seconds after it was frozen

    def sanitize(self) -> "Config":
        self.auto_unfreeze_seconds = max(MIN_SECONDS, min(MAX_SECONDS, self.auto_unfreeze_seconds))
        return self


def load(path: "Path | None" = None) -> Config:
    path = path or config_path()
    cfg = Config()
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return cfg
    if isinstance(data.get("auto_unfreeze"), bool):
        cfg.auto_unfreeze = data["auto_unfreeze"]
    v = data.get("auto_unfreeze_seconds")
    if isinstance(v, int) and not isinstance(v, bool):
        cfg.auto_unfreeze_seconds = v
    return cfg.sanitize()


def save(cfg: Config, path: "Path | None" = None) -> None:
    import tomli_w

    path = path or config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".toml.tmp")
    tmp.write_text(tomli_w.dumps({f.name: getattr(cfg, f.name) for f in fields(Config)}), encoding="utf-8")
    os.replace(tmp, path)


def mtime(path: "Path | None" = None) -> float:
    try:
        return (path or config_path()).stat().st_mtime
    except OSError:
        return 0.0
