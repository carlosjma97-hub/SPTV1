"""Logica de diagnostico y reinstalacion. Pura: solo habla con un Backend, asi se prueba sin Windows."""
from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Callable, Optional

from .backend_base import Backend, BackendError
from .models import SUPPORTED_KINDS, PrinterInfo

TOTAL_PHASES = 8

PHYSICAL_STATUSES = {
    "TonerLow": "Nivel de tóner bajo",
    "TonerEmpty": "Tóner agotado",
    "PaperEmpty": "Bandeja de papel vacía",
    "PaperOut": "Bandeja de papel vacía",
    "PaperJam": "Papel atascado",
    "DoorOpen": "Cubierta o puerta de la impresora abierta",
    "OutputBinFull": "Bandeja de salida llena",
    "UserIntervention": "Requiere intervención manual",
    "ManualFeed": "Alimentación manual requerida",
}

USER_ACTIONS = {
    1: "Verifique que la impresora siga instalada y reintente. Si persiste, avise a Sistemas.",
    2: "Verifique que la impresora este encendida y conectada a la red. Si esta bien, avise a Sistemas.",
    3: "Reinicie el equipo y reintente. Si persiste, avise a Sistemas.",
}
USER_ACTION_DEFAULT = ("No apague el equipo. Avise a Sistemas indicando la fase que fallo "
                       "y envie el registro (EXPORTAR REGISTRO).")


class WorkflowError(Exception):
    """Fallo controlado de una fase (mensaje apto para el funcionario)."""


@dataclass
class Result:
    state: str = "running"        # running | done | warning | error | rolledback
    message: str = ""
    phase: int = 0
    total: int = TOTAL_PHASES
    text: str = ""
    failed_phase: int = 0
    user_action: str = ""
    simulate: bool = False
    log: list = field(default_factory=list)
    warnings: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


def has_duplex(caps) -> bool:
    return any(str(c).startswith("TwoSided") for c in (caps or []))


# ------------------------------------------------------------------ diagnostico
def diagnose(b: Backend, name: str) -> tuple[list[str], str]:
    """Revision de solo lectura. Devuelve (lineas, conclusion)."""
    s = b.get_printer(name)
    lines: list[str] = []
    problems = 0

    def chk(ok: bool, text: str):
        nonlocal problems
        lines.append(("[OK]    " if ok else "[FALLO] ") + text)
        if not ok:
            problems += 1

    chk(b.spooler_running(), "Servicio Cola de impresion (Print Spooler) en ejecucion")
    if s.status in PHYSICAL_STATUSES:
        lines.append(f"[AVISO]  Estado informado por Windows: {s.status} ({PHYSICAL_STATUSES[s.status]} - revisar físico/consumible)")
    else:
        chk(s.status == "Normal", f"Estado informado por Windows: {s.status}")
    chk(s.driver_found, f"Controlador presente: {s.driver}")
    chk(s.port_found, f"Puerto presente: {s.port_name}")
    network = True
    if s.kind == "TCPIP":
        tcp_port = 515 if s.protocol == "LPR" else (s.port_number or 9100)
        ping, tcp = b.check_host(s.host, tcp_port)
        chk(ping, f"Ping a {s.host}")
        chk(tcp, f"Conexion TCP al puerto {tcp_port}")
        network = ping or tcp
    jobs = b.list_jobs(name)
    bad = [j for j in jobs if any(w in j.status for w in ("Error", "Blocked", "Offline", "Paper"))]
    chk(not bad, f"Trabajos en cola: {len(jobs)} (con error: {len(bad)})")
    caps = b.duplex_caps(name)
    if caps is None:
        lines.append("[INFO]  Duplex: no consultable")
    elif has_duplex(caps):
        lines.append(f"[INFO]  Duplex admitido. Predeterminado actual: {s.duplex_mode}")
    else:
        lines.append("[INFO]  El controlador no declara duplex")
    lines.append(f"[INFO]  Tipo de conexion: {s.kind}")

    if s.kind == "Compartida":
        c = "Impresora compartida de un servidor; no se reinstala localmente. Avise a Sistemas."
    elif s.kind not in SUPPORTED_KINDS:
        c = "Tipo no soportado para reinstalacion automatica. Avise a Sistemas."
    elif not network:
        c = "La impresora no responde en la red. Revise energia, cable/Wi-Fi o IP; reinstalar no lo resolvera."
    elif not s.driver_found:
        c = "Falta el controlador. Se requiere intervencion de Sistemas."
    elif problems:
        c = "Hay fallas locales. Se recomienda REINSTALAR IMPRESORA."
    elif s.status in PHYSICAL_STATUSES:
        c = f"Windows se comunica correctamente, pero el equipo reporta: {s.status} ({PHYSICAL_STATUSES[s.status]}). Requiere revisión física (tóner/papel/cubierta); reinstalar el software no solucionará esto."
    else:
        c = "Windows no detecta fallas. Si no imprime, haga la pagina de prueba y, si falla, reinstale."
    return lines, c


# ----------------------------------------------------------------- reinstalacion
def reinstall(b: Backend, name: str, *, simulate: bool = False,
              on_update: Optional[Callable[[Result], None]] = None,
              oplog: Optional[Callable[..., None]] = None, user: str = "",
              sleep: Callable[[float], None] = time.sleep, backup_dir=None) -> Result:
    """Ejecuta las 8 fases. Nunca lanza: devuelve un Result con el estado final."""
    t0 = time.monotonic()
    R = Result(simulate=simulate, text="Iniciando")

    def push():
        if on_update:
            on_update(R)

    def log(msg: str):
        R.log.append(msg)
        push()

    def step(n: int, text: str):
        R.phase, R.text = n, text
        log(f"[{n}/{TOTAL_PHASES}] {text}")

    def finish(state: str, op_result: str, message: str, host="", driver=""):
        R.state = state
        push()
        if oplog:
            oplog(printer=name, host=host, driver=driver,
                  operation="Simulacion" if simulate else "Reinstalacion", result=op_result,
                  phase=R.failed_phase, seconds=time.monotonic() - t0, message=message, user=user)

    snap: Optional[PrinterInfo] = None
    ticket: Optional[str] = None
    dup_before = None
    removed = False
    try:
        # FASE 1 - identificacion y respaldo
        step(1, "Guardando configuracion original")
        snap = b.get_printer(name)
        try:
            ticket = b.get_ticket(name)
        except BackendError:
            log("Aviso: no se pudo leer el perfil de impresion.")
        dup_before = b.duplex_caps(name)
        if backup_dir:
            _save_backup(backup_dir, snap, ticket)
        log(f"Impresora: {snap.name} | Controlador: {snap.driver} | Puerto: {snap.port_name} | Tipo: {snap.kind}")

        # FASE 2 - validacion (antes de tocar nada)
        step(2, "Verificando conexion de red y requisitos")
        if snap.kind == "Compartida":
            raise WorkflowError("Es una impresora compartida de un servidor: no se reinstala localmente.")
        if snap.kind not in SUPPORTED_KINDS:
            raise WorkflowError(f"Tipo de impresora no soportado para reinstalacion automatica: {snap.kind}.")
        if not snap.driver_found:
            raise WorkflowError(f"El controlador '{snap.driver}' no esta disponible en este equipo. "
                                "Se requiere intervencion de Sistemas.")
        if not snap.port_found:
            raise WorkflowError(f"No se pudo identificar el puerto '{snap.port_name}'.")
        if snap.kind == "TCPIP":
            tcp_port = 515 if snap.protocol == "LPR" else (snap.port_number or 9100)
            ping, tcp = b.check_host(snap.host, tcp_port)
            log(f"IP {snap.host}: ping={ping}, puerto TCP {tcp_port}={tcp}")
            if not (ping or tcp):
                raise WorkflowError(f"La impresora no responde en la red (IP {snap.host}). No se modifico nada.")
        if simulate:
            for t in ("Limpiaria solo los trabajos de esta impresora.",
                      "Retiraria unicamente esta impresora (no el controlador).",
                      "Reconstruiria el puerto con la misma IP/protocolo si ninguna otra impresora lo usa.",
                      f"Reinstalaria con el controlador '{snap.driver}' y el nombre original.",
                      "Restauraria preferencias y duplex si el controlador los admite.",
                      "Verificaria nombre, controlador, puerto y estado."):
                log(f"(simulacion) {t}")
            R.phase = TOTAL_PHASES
            R.message = "SIMULACION COMPLETADA: no se modifico nada."
            finish("done", "OK", "Simulacion sin cambios", snap.host, snap.driver)
            return R

        # FASE 3 - limpieza (solo esta impresora)
        step(3, "Limpiando trabajos pendientes de esta impresora")
        _clear_jobs(b, name, log, sleep)

        # FASE 4 - desinstalacion (solo esta impresora; ni controladores ni otros puertos)
        step(4, "Retirando impresora instalada")
        b.remove_printer(name)
        removed = True

        # FASE 5 - puerto
        step(5, "Reconstruyendo puerto")
        if snap.kind == "TCPIP":
            if b.printers_on_port(snap.port_name):
                log("El puerto lo usan otras impresoras: se conserva sin cambios.")
            else:
                b.remove_port(snap.port_name)
                sleep(2)
                b.add_port(snap)
                log(f"Puerto {snap.port_name} recreado ({snap.protocol} {snap.host}:{snap.port_number}).")
        else:
            log("Puerto USB: se reutiliza el existente.")

        # FASE 6 - reinstalacion con el MISMO controlador y nombre
        step(6, "Instalando controlador existente")
        b.add_printer(snap)
        log(f"Impresora '{snap.name}' creada con el controlador '{snap.driver}'.")

        # FASE 7 - preferencias y duplex (solo si el controlador lo admite)
        step(7, "Recuperando configuracion")
        restored = False
        if ticket:
            try:
                b.set_ticket(name, ticket)
                restored = True
                log("Perfil de impresion restaurado.")
            except BackendError as e:
                log(f"Aviso: no se restauro el perfil completo: {e}")
        if not restored and has_duplex(dup_before) and snap.duplex_mode.startswith(("OneSided", "TwoSided")):
            try:
                b.set_duplex(name, snap.duplex_mode)
                log(f"Duplex predeterminado restaurado: {snap.duplex_mode}.")
            except BackendError as e:
                log(f"Aviso: no se pudo restaurar el duplex: {e}")

        # FASE 8 - verificacion
        step(8, "Verificando funcionamiento")
        warn: list[str] = []
        try:
            p2 = b.get_printer(name)
        except BackendError:
            raise WorkflowError("Windows no muestra la impresora despues de reinstalarla.")
        if p2.name != snap.name:
            raise WorkflowError("El nombre de la impresora no coincide con el original.")
        if p2.driver != snap.driver:
            raise WorkflowError("El controlador instalado no coincide con el original.")
        if p2.port_name != snap.port_name:
            raise WorkflowError("El puerto instalado no coincide con el original.")
        if snap.kind == "TCPIP" and p2.host != snap.host:
            raise WorkflowError("El puerto no corresponde a la IP original.")
        if snap.kind == "TCPIP" and snap.snmp and not p2.snmp:
            warn.append("SNMP estaba habilitado originalmente y no pudo confirmarse.")
        if p2.status != "Normal":
            if p2.status in PHYSICAL_STATUSES:
                log(f"Aviso del equipo (físico/consumible): {p2.status} ({PHYSICAL_STATUSES[p2.status]})")
            else:
                warn.append(f"Estado de Windows: {p2.status}")
        if has_duplex(dup_before) and not has_duplex(b.duplex_caps(name)):
            warn.append("El duplex no fue reconocido tras reinstalar.")
        for w in warn:
            log(f"ADVERTENCIA: {w}")
        R.warnings = warn
        R.message = "IMPRESORA REINSTALADA CORRECTAMENTE"
        log("Instalacion verificada en Windows. La impresion fisica solo se confirma con la pagina de prueba.")
        finish("warning" if warn else "done", "OK", "; ".join(warn), snap.host, snap.driver)
        return R

    except (WorkflowError, BackendError, Exception) as exc:  # noqa: BLE001 - nunca debe escapar
        failed = R.phase
        log(f"ERROR en fase {failed}: {exc}")
        final = "error"
        if snap and removed and not simulate:
            log("Intentando restaurar la configuracion anterior...")
            try:
                _rollback(b, snap, ticket)
                log("Se restauro la impresora a su configuracion anterior.")
                final = "rolledback"
            except Exception as e2:  # noqa: BLE001
                log(f"No se pudo restaurar automaticamente: {e2}")
        R.failed_phase = failed
        R.message = f"NO SE PUDO REINSTALAR (fase {failed}): {exc}"
        R.user_action = USER_ACTIONS.get(failed, USER_ACTION_DEFAULT)
        finish(final, final, str(exc), snap.host if snap else "", snap.driver if snap else "")
        return R


def _clear_jobs(b: Backend, name: str, log, sleep) -> None:
    for j in b.list_jobs(name):
        try:
            b.remove_job(name, j.id)
        except BackendError:
            pass
    sleep(2)
    if not b.list_jobs(name):
        log("Cola de esta impresora limpia.")
        return
    log("Hay trabajos bloqueados: se reinicia el servicio Print Spooler "
        "(afecta unos segundos a todas las impresoras del equipo).")
    b.restart_spooler()
    sleep(4)
    for j in b.list_jobs(name):
        try:
            b.remove_job(name, j.id)
        except BackendError:
            pass
    if b.list_jobs(name):
        log("Aviso: quedan trabajos; se eliminaran junto con la cola al retirar la impresora.")


def _rollback(b: Backend, snap: PrinterInfo, ticket: Optional[str]) -> None:
    try:
        b.get_printer(snap.name)
        return  # la impresora existe: nada que restaurar
    except BackendError:
        pass
    if snap.kind == "TCPIP" and not b.port_exists(snap.port_name):
        b.add_port(snap)
    b.add_printer(snap)
    if ticket:
        try:
            b.set_ticket(snap.name, ticket)
        except BackendError:
            pass


def _save_backup(backup_dir, snap: PrinterInfo, ticket) -> None:
    import json
    import re
    from datetime import datetime
    from pathlib import Path
    try:
        Path(backup_dir).mkdir(parents=True, exist_ok=True)
        safe = re.sub(r"[^\w.-]", "_", snap.name)
        f = Path(backup_dir) / f"{datetime.now():%Y%m%d-%H%M%S}-{safe}.json"
        f.write_text(json.dumps({"printer": snap.to_dict(), "ticket": ticket}, ensure_ascii=False, indent=2),
                     encoding="utf-8")
    except OSError:
        pass
