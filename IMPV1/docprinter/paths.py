"""Carpetas de datos. Se pueden redirigir con DOCPRINTER_DATA (pruebas y desarrollo)."""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Dirs:
    root: Path

    @property
    def queue(self) -> Path: return self.root / "queue"
    @property
    def results(self) -> Path: return self.root / "results"
    @property
    def logs(self) -> Path: return self.root / "logs"
    @property
    def backups(self) -> Path: return self.root / "backups"
    @property
    def heartbeat(self) -> Path: return self.root / "heartbeat.txt"

    def ensure(self) -> "Dirs":
        for d in (self.root, self.queue, self.results, self.logs, self.backups):
            d.mkdir(parents=True, exist_ok=True)
        return self


def default_root() -> Path:
    env = os.environ.get("DOCPRINTER_DATA")
    if env:
        return Path(env)
    if os.name == "nt":
        return Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "DocPrinterTI"
    return Path.home() / ".docprinter-dev"


def get_dirs(root: Path | None = None) -> Dirs:
    return Dirs(Path(root) if root else default_root())


def get_desktop_dir() -> Path:
    """Obtiene la carpeta de Escritorio real del usuario (incluyendo OneDrive o espanol)."""
    home = Path.home()
    userprofile = os.environ.get("USERPROFILE")
    candidates = []
    if userprofile:
        up = Path(userprofile)
        candidates.extend([
            up / "OneDrive" / "Escritorio",
            up / "OneDrive" / "Desktop",
            up / "Escritorio",
            up / "Desktop",
        ])
    candidates.extend([
        home / "OneDrive" / "Escritorio",
        home / "OneDrive" / "Desktop",
        home / "Escritorio",
        home / "Desktop",
    ])
    for c in candidates:
        if c.exists() and c.is_dir():
            return c
    return home
