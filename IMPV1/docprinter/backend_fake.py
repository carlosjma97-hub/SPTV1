"""Backend simulado en memoria: permite ejecutar y probar TODO sin Windows ni impresoras."""
from __future__ import annotations

import copy
from typing import Optional

from .backend_base import Backend, BackendError, PrinterNotFound
from .models import Job, PrinterInfo

MUTATING = {"remove_job", "restart_spooler", "remove_printer", "remove_port",
            "add_port", "add_printer", "set_ticket", "set_duplex"}


class FakeBackend(Backend):
    def __init__(self):
        self.printers: dict[str, PrinterInfo] = {}
        self.drivers: set[str] = set()
        self.ports: set[str] = set()
        self.jobs: dict[str, list[Job]] = {}
        self.tickets: dict[str, str] = {}
        self.caps_by_driver: dict[str, list[str]] = {}
        self.hosts: dict[str, tuple[bool, bool]] = {}
        self.stuck: set[str] = set()          # impresoras cuyos trabajos solo se borran tras reiniciar el spooler
        self.fail: dict[str, Exception] = {}  # metodo -> excepcion a lanzar (inyeccion de fallos)
        self.drop_duplex_after_reinstall = False
        self.reinstalled: set[str] = set()
        self.default = ""
        self.spooler = True
        self.calls: list[tuple] = []

    # ---- utilidades de prueba ----
    def _rec(self, method: str, *args):
        self.calls.append((method, *args))
        if method in self.fail:
            raise self.fail.pop(method)

    def mutations(self) -> list[tuple]:
        return [c for c in self.calls if c[0] in MUTATING]

    def add_demo_printer(self, name, driver, host="", port=None, kind="TCPIP", duplex=True, **kw) -> PrinterInfo:
        port_name = port or (f"IP_{host}" if host else "USB001")
        p = PrinterInfo(name=name, driver=driver, port_name=port_name, kind=kind, host=host,
                        port_number=9100 if host else 0, protocol="RAW" if host else "",
                        duplex_mode="TwoSidedLongEdge" if duplex else "OneSided", **kw)
        self.printers[name] = p
        self.drivers.add(driver)
        self.ports.add(port_name)
        self.caps_by_driver.setdefault(driver, ["OneSided", "TwoSidedLongEdge", "TwoSidedShortEdge"] if duplex else ["OneSided"])
        self.tickets[name] = "<ticket duplex='TwoSidedLongEdge'/>" if duplex else "<ticket/>"
        self.hosts.setdefault(host, (True, True)) if host else None
        self.jobs.setdefault(name, [])
        return p

    @classmethod
    def demo(cls) -> "FakeBackend":
        b = cls()
        b.add_demo_printer("HP LaserJet Contabilidad", "HP Universal Printing PCL 6", host="10.0.0.21", manufacturer="HP")
        b.add_demo_printer("Ricoh Sistemas", "RICOH MP C3004 PCL 6", host="10.0.0.35", manufacturer="RICOH")
        b.add_demo_printer("Brother Recepcion", "Brother HL-L2350DW", kind="USB", duplex=False, manufacturer="Brother")
        b.add_demo_printer("Canon Servidor", "Canon Generic Plus", port="\\\\SRV01\\Canon", kind="Compartida")
        b.printers["Canon Servidor"].status = "Normal"
        b.add_demo_printer("Epson Apagada", "EPSON WF-C5790", host="10.0.0.99", manufacturer="EPSON")
        b.hosts["10.0.0.99"] = (False, False)
        b.default = "Ricoh Sistemas"
        return b

    # ---- lectura ----
    def list_printers(self): self._rec("list_printers"); return [copy.deepcopy(p) for p in self.printers.values()]

    def get_printer(self, name):
        self._rec("get_printer", name)
        if name not in self.printers:
            raise PrinterNotFound(f"No existe la impresora '{name}'.")
        p = copy.deepcopy(self.printers[name])
        p.driver_found = p.driver in self.drivers
        p.port_found = p.port_name in self.ports or p.kind == "Compartida"
        return p

    def get_ticket(self, name):
        self._rec("get_ticket", name)
        if name not in self.tickets:
            raise BackendError("sin perfil")
        return self.tickets[name]

    def duplex_caps(self, name) -> Optional[list[str]]:
        self._rec("duplex_caps", name)
        p = self.printers.get(name)
        if not p:
            return None
        if name in self.reinstalled and self.drop_duplex_after_reinstall:
            return ["OneSided"]
        return list(self.caps_by_driver.get(p.driver, []))

    def list_jobs(self, name): self._rec("list_jobs", name); return list(self.jobs.get(name, []))
    def printers_on_port(self, port_name): self._rec("printers_on_port", port_name); return [n for n, p in self.printers.items() if p.port_name == port_name]
    def port_exists(self, port_name): self._rec("port_exists", port_name); return port_name in self.ports
    def spooler_running(self): return self.spooler
    def check_host(self, host, port): self._rec("check_host", host, port); return self.hosts.get(host, (True, True))
    def default_printer(self): return self.default
    def file_owner(self, path): return "EQUIPO\\funcionario"

    # ---- escritura ----
    def remove_job(self, name, job_id):
        self._rec("remove_job", name, job_id)
        if name in self.stuck:
            return
        self.jobs[name] = [j for j in self.jobs.get(name, []) if j.id != job_id]

    def restart_spooler(self):
        self._rec("restart_spooler")
        self.stuck.clear()

    def remove_printer(self, name):
        self._rec("remove_printer", name)
        if name not in self.printers:
            raise PrinterNotFound(name)
        del self.printers[name]
        self.tickets.pop(name, None)
        self.jobs.pop(name, None)

    def rename_printer(self, old_name, new_name):
        self._rec("rename_printer", old_name, new_name)
        if old_name not in self.printers:
            raise PrinterNotFound(old_name)
        if new_name in self.printers:
            raise BackendError("Ya existe una impresora con ese nombre")
        p = self.printers.pop(old_name)
        p.name = new_name
        self.printers[new_name] = p
        if old_name in self.tickets:
            self.tickets[new_name] = self.tickets.pop(old_name)
        if old_name in self.jobs:
            self.jobs[new_name] = self.jobs.pop(old_name)
        if self.default == old_name:
            self.default = new_name

    def remove_port(self, port_name):
        self._rec("remove_port", port_name)
        if any(p.port_name == port_name for p in self.printers.values()):
            raise BackendError("El puerto esta en uso")
        self.ports.discard(port_name)

    def add_port(self, p):
        self._rec("add_port", p.port_name)
        if p.port_name in self.ports:
            raise BackendError("El puerto ya existe")
        self.ports.add(p.port_name)

    def add_printer(self, p):
        self._rec("add_printer", p.name)
        if p.driver not in self.drivers:
            raise BackendError("Controlador no instalado")
        if p.port_name not in self.ports:
            raise BackendError("El puerto no existe")
        if p.name in self.printers:
            raise BackendError("La impresora ya existe")
        self.printers[p.name] = copy.deepcopy(p)
        self.printers[p.name].duplex_mode = "OneSided"
        self.tickets[p.name] = "<ticket/>"
        self.jobs[p.name] = []
        self.reinstalled.add(p.name)

    def set_ticket(self, name, xml):
        self._rec("set_ticket", name)
        self.tickets[name] = xml
        if "TwoSided" in xml:
            self.printers[name].duplex_mode = "TwoSidedLongEdge"

    def set_duplex(self, name, mode):
        self._rec("set_duplex", name, mode)
        self.printers[name].duplex_mode = mode

    def set_default_printer(self, name): self._rec("set_default_printer", name); self.default = name
    def print_test_page(self, name): self._rec("print_test_page", name)
