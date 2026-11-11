"""Backend real de Windows. Usa cmdlets de PowerShell con scripts FIJOS; los parametros viajan como JSON
(archivo temporal), nunca se concatenan dentro del texto del script -> no hay inyeccion de comandos."""
from __future__ import annotations

import base64
import json
import os
import re
import socket
import subprocess
import tempfile
from typing import Optional

from .backend_base import Backend, BackendError, PrinterNotFound
from .models import Job, PrinterInfo, classify

CREATE_NO_WINDOW = 0x08000000
DUPLEX_MODES = ("OneSided", "TwoSidedLongEdge", "TwoSidedShortEdge")
_HOST_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,252}$")


def powershell_exe() -> str:
    """PowerShell de 64 bits aunque este proceso sea de 32 bits (Sysnative)."""
    root = os.environ.get("SystemRoot", r"C:\Windows")
    sysnative = os.path.join(root, "Sysnative", "WindowsPowerShell", "v1.0", "powershell.exe")
    if os.path.exists(sysnative):
        return sysnative
    return os.path.join(root, "System32", "WindowsPowerShell", "v1.0", "powershell.exe")


def run_ps(script: str, params: Optional[dict] = None, timeout: int = 120) -> str:
    """Ejecuta un script PowerShell fijo. Parametros disponibles dentro como $p."""
    prelude = ("$ErrorActionPreference='Stop'\n"
               "[Console]::OutputEncoding=[Text.Encoding]::UTF8\n"
               "$OutputEncoding=[Text.Encoding]::UTF8\n"
               "$p = Get-Content -Raw -Encoding UTF8 -LiteralPath $env:DPTI_PARAMS_FILE | ConvertFrom-Json\n")
    encoded = base64.b64encode((prelude + script).encode("utf-16-le")).decode("ascii")
    fd, pfile = tempfile.mkstemp(suffix=".json", prefix="dpti_")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(params or {}, fh)
        env = dict(os.environ, DPTI_PARAMS_FILE=pfile)
        cp = subprocess.run([powershell_exe(), "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                             "-EncodedCommand", encoded], capture_output=True, env=env, timeout=timeout,
                            creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
    except subprocess.TimeoutExpired as e:
        raise BackendError("PowerShell tardo demasiado en responder.") from e
    except OSError as e:
        raise BackendError(f"No se pudo ejecutar PowerShell: {e}") from e
    finally:
        try:
            os.remove(pfile)
        except OSError:
            pass
    out = cp.stdout.decode("utf-8", "replace")
    if cp.returncode != 0:
        err = cp.stderr.decode("utf-8", "replace").strip() or out.strip() or f"codigo {cp.returncode}"
        # Parser robusto para errores CLIXML de PowerShell
        if "#< CLIXML" in err:
            try:
                import xml.etree.ElementTree as ET
                import html
                xml_index = err.find("#< CLIXML")
                xml_text = err[xml_index + len("#< CLIXML"):].strip()
                root = ET.fromstring(xml_text)
                messages = [html.unescape(node.text or "").replace("_x000D__x000A_", " ").strip()
                            for node in root.iter() if node.tag.endswith("S") and node.attrib.get("S") == "Error"]
                err = next((message for message in messages if message), err)
            except Exception:
                err = err.replace("#< CLIXML", "").strip()
        raise BackendError(err.splitlines()[0] if err else err)
    return out


def _json(out: str, default):
    out = out.strip().lstrip("\ufeff")
    return json.loads(out) if out else default


_LIST = r"""
$ports=@{}; Get-PrinterPort -ErrorAction SilentlyContinue | ForEach-Object { $ports[$_.Name]=$_ }
$drivers=@{}; Get-PrinterDriver -ErrorAction SilentlyContinue | ForEach-Object { $drivers[$_.Name]=$_ }
$out=@()
foreach($x in @(Get-Printer)){
  if ($p.name -and $x.Name -ne $p.name) { continue }
  $po=$ports[$x.PortName]; $dr=$drivers[$x.DriverName]
  $poHost=[string]$po.PrinterHostAddress; $poNumber=[int]$po.PortNumber
  $poProto=("$($po.Protocol)"); $poSnmp=[bool]$po.SNMPEnabled
  $poComm=[string]$po.SNMPCommunity; $poIdx=[int]$po.SNMPIndex
  if (-not $poHost) {
    $reg = Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Control\Print\Monitors\*\Ports\$($x.PortName)" -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($reg) {
      $hpHost = if ($reg.IPAddress) { $reg.IPAddress } else { $reg.HostName }
      if ($hpHost) {
        $poHost = [string]$hpHost; $poNumber = if ($reg.PortNumber) { [int]$reg.PortNumber } else { 9100 }
        $poProto = if ($reg.Protocol -eq 2) { "LPR" } else { "RAW" }
        $poSnmp = [bool]$reg.'SNMP Enabled'
        if ($reg.'SNMP Community') { $poComm = [string]$reg.'SNMP Community' }
        if ($reg.'SNMP Index') { $poIdx = [int]$reg.'SNMP Index' }
      }
    }
  }
  $out += [pscustomobject]@{ name=$x.Name; driver=$x.DriverName; driver_found=[bool]$dr; manufacturer=[string]$dr.Manufacturer
    port_name=$x.PortName; port_found=[bool]($po -or $poHost); type=$x.Type.ToString(); status=$x.PrinterStatus.ToString()
    shared=[bool]$x.Shared; share_name=[string]$x.ShareName; location=[string]$x.Location; comment=[string]$x.Comment
    host=$poHost; number=$poNumber; protocol=$poProto; snmp=$poSnmp
    community=$poComm; index=$poIdx; lpr_queue=[string]$po.LprQueueName; lpr_bc=[bool]$po.LprByteCounting }
}
ConvertTo-Json -InputObject @($out) -Depth 3 -Compress
"""
_DUPLEX_MODE = r"""(Get-PrintConfiguration -PrinterName $p.name).DuplexingMode.ToString()"""
_TICKET = r"""(Get-PrintConfiguration -PrinterName $p.name).PrintTicketXML"""
_CAPS = r"""
Add-Type -AssemblyName System.Printing
$srv = New-Object System.Printing.LocalPrintServer
$q = $srv.GetPrintQueue($p.name)
$r = @($q.GetPrintCapabilities().DuplexingCapability | ForEach-Object { $_.ToString() })
$q.Dispose(); $srv.Dispose()
ConvertTo-Json -InputObject @($r) -Compress
"""
_JOBS = r"""
$j=@(Get-PrintJob -PrinterName $p.name -ErrorAction SilentlyContinue | ForEach-Object { [pscustomobject]@{id=[int]$_.Id; status="$($_.JobStatus)"} })
ConvertTo-Json -InputObject @($j) -Compress
"""
_ADD_PORT = r"""
$portName = $p.port_name
if (-not (Get-PrinterPort -Name $portName -ErrorAction SilentlyContinue)) {
  if ($p.protocol -eq 'LPR') {
    $a=@{Name=$portName; LprHostAddress=$p.host; LprQueueName=$p.lpr_queue}
    if ($p.lpr_byte_counting) { $a.LprByteCounting=$true }
  } else {
    $pn = if ([int]$p.port_number -gt 0) { [int]$p.port_number } else { 9100 }
    $a=@{Name=$portName; PrinterHostAddress=$p.host; PortNumber=$pn}
    if ($p.snmp) { $a.SNMP=[int]$p.snmp_index; $a.SNMPCommunity=[string]$p.snmp_community }
  }
  Add-PrinterPort @a
}
"""
_ADD_PRINTER = r"""
$a=@{Name=$p.name; DriverName=$p.driver; PortName=$p.port_name}
if ($p.location) { $a.Location=$p.location }
if ($p.comment)  { $a.Comment=$p.comment }
if ($p.shared -and $p.share_name) { $a.Shared=$true; $a.ShareName=$p.share_name }
Add-Printer @a
"""


class WindowsBackend(Backend):
    # ---- lectura ----
    def _to_info(self, d: dict) -> PrinterInfo:
        host = d.get("host") or ""
        return PrinterInfo(
            name=d["name"], driver=d["driver"], driver_found=bool(d["driver_found"]),
            manufacturer=d.get("manufacturer", ""), port_name=d["port_name"], port_found=bool(d["port_found"]),
            kind=classify(d.get("type", ""), d["port_name"], d["driver"], host), status=d.get("status", ""),
            shared=bool(d.get("shared")), share_name=d.get("share_name", ""), location=d.get("location", ""),
            comment=d.get("comment", ""), host=host, port_number=int(d.get("number") or 0),
            protocol=("LPR" if re.search(r"2|LPR", str(d.get("protocol", ""))) else "RAW") if host else "",
            snmp=bool(d.get("snmp")), snmp_community=d.get("community") or "public",
            snmp_index=int(d.get("index") or 1), lpr_queue=d.get("lpr_queue", ""),
            lpr_byte_counting=bool(d.get("lpr_bc")))

    def list_printers(self):
        return [self._to_info(d) for d in _json(run_ps(_LIST, {"name": ""}), [])]

    def get_printer(self, name):
        rows = _json(run_ps(_LIST, {"name": name}), [])
        if not rows:
            raise PrinterNotFound(f"No existe la impresora '{name}'.")
        info = self._to_info(rows[0])
        try:
            info.duplex_mode = run_ps(_DUPLEX_MODE, {"name": name}).strip() or "Desconocido"
        except BackendError:
            info.duplex_mode = "Desconocido"
        return info

    def get_ticket(self, name):
        out = run_ps(_TICKET, {"name": name}).strip()
        return out or None

    def duplex_caps(self, name):
        try:
            return [str(x) for x in _json(run_ps(_CAPS, {"name": name}), [])]
        except (BackendError, ValueError):
            return None

    def list_jobs(self, name):
        return [Job(int(j["id"]), j.get("status", "")) for j in _json(run_ps(_JOBS, {"name": name}), [])]

    def printers_on_port(self, port_name):
        return [p.name for p in self.list_printers() if p.port_name == port_name]

    def port_exists(self, port_name):
        out = run_ps("@(Get-PrinterPort -Name $p.name -ErrorAction SilentlyContinue).Count", {"name": port_name})
        return out.strip() not in ("", "0")

    def spooler_running(self):
        return run_ps("(Get-Service -Name Spooler).Status.ToString()").strip() == "Running"

    def check_host(self, host, port):
        if not _HOST_RE.match(host or ""):
            return (False, False)
        tcp = False
        try:
            with socket.create_connection((host, int(port)), timeout=2.5):
                tcp = True
        except OSError:
            pass
        ping = False
        try:
            r = subprocess.run(["ping", "-n", "1", "-w", "1500", host], capture_output=True, timeout=8,
                               creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)
            ping = r.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
        return (ping, tcp)

    def default_printer(self):
        try:
            return run_ps('(Get-CimInstance -ClassName Win32_Printer -Filter "Default=$true" | Select-Object -First 1).Name').strip()
        except BackendError:
            return ""

    def file_owner(self, path):
        try:
            return run_ps("(Get-Acl -LiteralPath $p.path).Owner", {"path": path}).strip() or "desconocido"
        except BackendError:
            return "desconocido"

    # ---- escritura ----
    def remove_job(self, name, job_id):
        run_ps("Remove-PrintJob -PrinterName $p.name -ID ([int]$p.id)", {"name": name, "id": int(job_id)})

    def restart_spooler(self):
        run_ps("Restart-Service -Name Spooler -Force")

    def remove_printer(self, name):
        run_ps("Remove-Printer -Name $p.name", {"name": name})

    def rename_printer(self, old_name, new_name):
        run_ps("Rename-Printer -Name $p.old_name -NewName $p.new_name", {"old_name": old_name, "new_name": new_name})

    def remove_port(self, port_name):
        run_ps("Remove-PrinterPort -Name $p.name", {"name": port_name})

    def add_port(self, p: PrinterInfo):
        run_ps(_ADD_PORT, p.to_dict())

    def add_printer(self, p: PrinterInfo):
        run_ps(_ADD_PRINTER, p.to_dict())

    def set_ticket(self, name, xml):
        run_ps("Set-PrintConfiguration -PrinterName $p.name -PrintTicketXml $p.xml", {"name": name, "xml": xml})

    def set_duplex(self, name, mode):
        if mode not in DUPLEX_MODES:
            raise BackendError(f"Modo duplex no valido: {mode}")
        run_ps("Set-PrintConfiguration -PrinterName $p.name -DuplexingMode $p.mode", {"name": name, "mode": mode})

    # ---- contexto de usuario ----
    def set_default_printer(self, name):
        run_ps("(New-Object -ComObject WScript.Network).SetDefaultPrinter($p.name)", {"name": name})

    def print_test_page(self, name):
        subprocess.Popen(["rundll32.exe", "printui.dll,PrintUIEntry", "/k", "/n", name],
                         creationflags=CREATE_NO_WINDOW if os.name == "nt" else 0)