"""Comunicacion GUI -> helper mediante archivos JSON en una cola. Validacion estricta de cada solicitud."""
from __future__ import annotations

import json
import os
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .paths import Dirs

UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-([0-9a-fA-F]{4}-){3}[0-9a-fA-F]{12}$")
OPERATIONS = ("Reinstall", "Simulate", "Remove", "Rename")
MAX_REQUEST_BYTES = 4096


@dataclass
class Request:
    id: str
    operation: str
    printer: str
    new_name: str = ""


def submit(dirs: Dirs, printer: str, operation: str, new_name: str = "") -> str:
    rid = str(uuid.uuid4())
    tmp = dirs.queue / f"{rid}.tmp"
    payload = {"id": rid, "operation": operation, "printerName": printer}
    if new_name:
        payload["newName"] = new_name
    tmp.write_text(json.dumps(payload), encoding="utf-8")
    os.replace(tmp, dirs.queue / f"{rid}.json")   # el helper solo mira *.json: nunca lee archivos a medias
    return rid


def parse_request(path: Path) -> Request:
    """Valida el archivo. Lanza ValueError si algo no cumple la lista blanca."""
    rid = path.stem
    if not UUID_RE.match(rid):
        raise ValueError("Nombre de solicitud invalido.")
    if path.stat().st_size > MAX_REQUEST_BYTES:
        raise ValueError("Solicitud demasiado grande.")
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ValueError("Solicitud ilegible.") from e
    if not isinstance(data, dict) or data.get("id") != rid:
        raise ValueError("Identificador no coincide.")
    op, name = data.get("operation"), data.get("printerName")
    if op not in OPERATIONS:
        raise ValueError("Operacion no permitida.")
    if not isinstance(name, str) or not name or len(name) > 200 or re.search(r"[\x00-\x1f]", name):
        raise ValueError("Nombre de impresora invalido.")
    new_name = data.get("newName", "")
    if op == "Rename":
        if not isinstance(new_name, str) or not new_name.strip() or len(new_name) > 200 or re.search(r"[\x00-\x1f\\/,]", new_name):
            raise ValueError("Nuevo nombre de impresora invalido.")
        new_name = new_name.strip()
    return Request(rid, op, name, new_name)


def write_result(dirs: Dirs, rid: str, data: dict) -> None:
    tmp = dirs.results / f"{rid}.tmp"
    tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, dirs.results / f"{rid}.json")


def read_result(dirs: Dirs, rid: str) -> Optional[dict]:
    f = dirs.results / f"{rid}.json"
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None
