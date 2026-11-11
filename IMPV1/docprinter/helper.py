"""Componente administrativo: corre como SYSTEM (tarea programada). Procesa solicitudes de la cola.
Solo ejecuta 'Reinstall' o 'Simulate' sobre impresoras que EXISTEN en el equipo."""
from __future__ import annotations

import os
import sys
import threading
import time
from datetime import datetime, timedelta

from . import ipc, oplog
from .backend_base import Backend, BackendError
from .paths import Dirs, get_dirs
from .workflow import Result, reinstall


def _reject(dirs: Dirs, rid: str, msg: str, user: str) -> None:
    r = Result(state="error", text="Solicitud rechazada", message=msg, user_action="Avise a Sistemas.", log=[msg])
    ipc.write_result(dirs, rid, r.to_dict())
    oplog.write(dirs.logs, operation="Rechazada", result="error", message=msg, user=user)


def process_request(b: Backend, dirs: Dirs, path, sleep=time.sleep) -> None:
    rid = path.stem
    user = "desconocido"
    try:
        user = b.file_owner(str(path))
    except Exception:  # noqa: BLE001
        pass
    try:
        req = ipc.parse_request(path)
    except ValueError as e:
        _remove(path)
        if ipc.UUID_RE.match(rid):
            _reject(dirs, rid, f"Solicitud invalida: {e}", user)
        return
    _remove(path)  # se consume antes de ejecutar: nunca se procesa dos veces
    try:
        # Se usa el nombre que reporta el sistema, no el texto recibido
        match = next((p for p in b.list_printers() if p.name == req.printer), None)
    except BackendError as e:
        _reject(dirs, rid, f"No se pudo leer la lista de impresoras: {e}", user)
        return
    if match is None:
        _reject(dirs, rid, "La impresora ya no esta instalada en este equipo.", user)
        return

    if req.operation == "Remove":
        try:
            b.remove_printer(match.name)
            r = Result(state="done", phase=8, text="Impresora eliminada",
                       message=f"Se elimino la impresora '{match.name}' correctamente.",
                       log=[f"Impresora '{match.name}' eliminada del equipo."])
            ipc.write_result(dirs, rid, r.to_dict())
            oplog.write(dirs.logs, printer=match.name, operation="Eliminar", result="OK",
                        message="Impresora eliminada", user=user)
            heartbeat(dirs)
        except Exception as e:  # noqa: BLE001
            _reject(dirs, rid, f"Error al eliminar impresora: {e}", user)
        return

    if req.operation == "Rename":
        try:
            b.rename_printer(match.name, req.new_name)
            r = Result(state="done", phase=8, text="Impresora renombrada",
                       message=f"Impresora renombrada a '{req.new_name}' correctamente.",
                       log=[f"Impresora '{match.name}' renombrada a '{req.new_name}'."])
            ipc.write_result(dirs, rid, r.to_dict())
            oplog.write(dirs.logs, printer=req.new_name, operation="Renombrar", result="OK",
                        message=f"Renombrada desde '{match.name}'", user=user)
            heartbeat(dirs)
        except Exception as e:  # noqa: BLE001
            _reject(dirs, rid, f"Error al renombrar impresora: {e}", user)
        return

    def _on_update(r):
        ipc.write_result(dirs, rid, r.to_dict())
        heartbeat(dirs)

    reinstall(b, match.name, simulate=(req.operation == "Simulate"),
              on_update=_on_update,
              oplog=lambda **kw: oplog.write(dirs.logs, **kw), user=user, sleep=sleep,
              backup_dir=dirs.backups)


def _remove(path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def heartbeat(dirs: Dirs) -> None:
    try:
        dirs.heartbeat.write_text(datetime.now().isoformat(), encoding="utf-8")
    except OSError:
        pass


def process_queue_once(b: Backend, dirs: Dirs, sleep=time.sleep) -> int:
    heartbeat(dirs)
    files = sorted(dirs.queue.glob("*.json"), key=lambda p: p.stat().st_mtime)
    for f in files:
        try:
            process_request(b, dirs, f, sleep)
        except Exception as e:  # noqa: BLE001 - el helper nunca debe morir
            oplog.write(dirs.logs, operation="Error interno", result="error", message=repr(e))
    return len(files)


def cleanup_results(dirs: Dirs, days: int = 3) -> None:
    limit = (datetime.now() - timedelta(days=days)).timestamp()
    for f in dirs.results.glob("*.json"):
        try:
            if f.stat().st_mtime < limit:
                f.unlink()
        except OSError:
            pass


def run_loop(b: Backend, dirs: Dirs, stop: threading.Event | None = None, interval: float = 2.0,
             sleep=time.sleep) -> None:
    stop = stop or threading.Event()
    cleanup_results(dirs)
    while not stop.is_set():
        try:
            process_queue_once(b, dirs, sleep)
        except Exception as e:  # noqa: BLE001 - el bucle nunca debe morir
            oplog.write(dirs.logs, operation="Error bucle helper", result="error", message=repr(e))
        stop.wait(interval)


def _single_instance() -> bool:
    if os.name != "nt":
        return True
    import ctypes
    ctypes.windll.kernel32.CreateMutexW(None, False, "Global\\DocPrinterTIHelper")
    return ctypes.windll.kernel32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def main(argv: list[str], fake: bool = False) -> int:
    from .backends import get_backend
    once = "--once" in argv
    if not _single_instance():
        return 0
    dirs = get_dirs().ensure()
    b = get_backend(fake)
    if once:
        n = process_queue_once(b, dirs)
        print(f"Solicitudes procesadas: {n}") if sys.stdout else None
        return 0
    run_loop(b, dirs)
    return 0
