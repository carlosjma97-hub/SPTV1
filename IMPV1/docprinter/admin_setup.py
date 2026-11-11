"""Configuracion administrativa (instalar/desinstalar/estado). Usa solo programas nativos (icacls, schtasks):
no depende de modulos de PowerShell ni de la arquitectura (32/64 bits) del proceso que lo invoca."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional
from xml.sax.saxutils import escape

from .paths import Dirs, get_dirs

TASK_NAME = "DocPrinterTI-Helper"
SYSTEM, ADMINS, USERS = "*S-1-5-18", "*S-1-5-32-544", "*S-1-5-32-545"   # SID: no dependen del idioma
CREATE_NO_WINDOW = 0x08000000


def log_path() -> Path:
    base = os.environ.get("ProgramData") if os.name == "nt" else None
    return Path(base or tempfile.gettempdir()) / "DocPrinterTI-instalacion.log"


def log(msg: str) -> None:
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    if sys.stdout:
        print(msg)
    try:
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass


def helper_command() -> tuple[str, str, str]:
    """(ejecutable, argumentos, carpeta de trabajo) con que se lanzara el helper."""
    if getattr(sys, "frozen", False):
        return sys.executable, "helper", str(Path(sys.executable).parent)
    return sys.executable, "-m docprinter helper", str(Path(__file__).resolve().parent.parent)


def task_xml(command: str, arguments: str, workdir: str) -> str:
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>DocPrinter TI - componente administrativo (solo operaciones predefinidas).</Description></RegistrationInfo>
  <Triggers><BootTrigger><Enabled>true</Enabled></BootTrigger></Triggers>
  <Principals><Principal id="Author"><UserId>S-1-5-18</UserId><RunLevel>HighestAvailable</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <Enabled>true</Enabled>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <RestartOnFailure><Interval>PT1M</Interval><Count>5</Count></RestartOnFailure>
  </Settings>
  <Actions Context="Author"><Exec>
    <Command>{escape(command)}</Command>
    <Arguments>{escape(arguments)}</Arguments>
    <WorkingDirectory>{escape(workdir)}</WorkingDirectory>
  </Exec></Actions>
</Task>
"""


def acl_commands(d: Dirs) -> list[list[str]]:
    def cmd(path: Path, *extra: str) -> list[str]:
        return ["icacls", str(path), "/inheritance:r", "/grant:r", f"{SYSTEM}:(OI)(CI)F", f"{ADMINS}:(OI)(CI)F", *extra]
    return [cmd(d.root, f"{USERS}:(OI)(CI)RX"),      # usuarios leen el latido
            cmd(d.queue, f"{USERS}:(OI)(CI)M"),      # usuarios solo depositan solicitudes
            cmd(d.results, f"{USERS}:(OI)(CI)RX"),
            cmd(d.logs, f"{USERS}:(OI)(CI)RX"),
            cmd(d.backups)]                          # solo SYSTEM y administradores


Runner = Callable[..., "subprocess.CompletedProcess"]


def _run(run: Runner, cmd: list[str], check: bool = True):
    cp = run(cmd, capture_output=True, text=True, creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    if check and cp.returncode != 0:
        raise RuntimeError(f"{' '.join(cmd[:2])} fallo (codigo {cp.returncode}): {(cp.stderr or cp.stdout).strip()}")
    return cp


def install(dirs: Optional[Dirs] = None, run: Runner = subprocess.run, wait_seconds: int = 15) -> int:
    d = dirs or get_dirs()
    try:
        log(f"Instalando componente administrativo | proceso 64 bits={sys.maxsize > 2**32}")
        d.ensure()
        for c in acl_commands(d):
            _run(run, c)
        log("Permisos aplicados.")
        _run(run, ["schtasks", "/End", "/TN", TASK_NAME], check=False)
        _run(run, ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], check=False)
        command, arguments, workdir = helper_command()
        fd, xml_file = tempfile.mkstemp(suffix=".xml", prefix="dpti_task_")
        os.close(fd)
        try:
            Path(xml_file).write_text(task_xml(command, arguments, workdir), encoding="utf-16")
            _run(run, ["schtasks", "/Create", "/TN", TASK_NAME, "/XML", xml_file, "/F"])
        finally:
            try:
                os.remove(xml_file)
            except OSError:
                pass
        log("Tarea programada registrada (SYSTEM, al iniciar el equipo).")
        _run(run, ["schtasks", "/Run", "/TN", TASK_NAME])
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            if d.heartbeat.exists() and time.time() - d.heartbeat.stat().st_mtime < 10:
                log("Componente administrativo ACTIVO.")
                return 0
            time.sleep(1)
        log("AVISO: la tarea se registro pero el componente aun no responde. Revise el Programador de tareas.")
        return 0
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {e}")
        return 1


def uninstall(keep_logs: bool = False, dirs: Optional[Dirs] = None, run: Runner = subprocess.run) -> int:
    import shutil
    d = dirs or get_dirs()
    try:
        _run(run, ["schtasks", "/End", "/TN", TASK_NAME], check=False)
        _run(run, ["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], check=False)
        if keep_logs:
            for sub in (d.queue, d.results, d.backups):
                shutil.rmtree(sub, ignore_errors=True)
            d.heartbeat.unlink(missing_ok=True)
        else:
            shutil.rmtree(d.root, ignore_errors=True)
        log("Componente administrativo retirado. No se eliminaron impresoras, controladores ni puertos.")
        return 0
    except Exception as e:  # noqa: BLE001
        log(f"ERROR: {e}")
        return 1


def status(dirs: Optional[Dirs] = None, run: Runner = subprocess.run) -> list[str]:
    d = dirs or get_dirs()
    out = []
    cp = _run(run, ["schtasks", "/Query", "/TN", TASK_NAME], check=False)
    out.append("Tarea del componente administrativo: " + ("INSTALADA" if cp.returncode == 0 else "NO INSTALADA"))
    age = (time.time() - d.heartbeat.stat().st_mtime) if d.heartbeat.exists() else None
    out.append("Latido: " + (f"hace {int(age)} s ({'ACTIVO' if age < 20 else 'SIN RESPUESTA'})" if age is not None else "sin latido"))
    return out


def main(argv: list[str]) -> int:
    action = argv[0] if argv else "status"
    if action == "install":
        return install()
    if action == "uninstall":
        return uninstall(keep_logs="--keep-logs" in argv)
    if action == "status":
        for line in status():
            log(line)
        return 0
    log("Uso: setup install | uninstall [--keep-logs] | status")
    return 2
