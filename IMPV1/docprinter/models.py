"""Modelos de datos puros (sin dependencias de Windows)."""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass

SUPPORTED_KINDS = ("TCPIP", "USB")  # tipos que se pueden reinstalar automaticamente


@dataclass
class PrinterInfo:
    name: str
    driver: str
    port_name: str
    kind: str = "Otro"            # TCPIP | USB | Compartida | Virtual | WSD | Otro
    status: str = "Normal"
    driver_found: bool = True
    port_found: bool = True
    manufacturer: str = ""
    shared: bool = False
    share_name: str = ""
    location: str = ""
    comment: str = ""
    host: str = ""
    port_number: int = 0
    protocol: str = ""            # RAW | LPR | ""
    snmp: bool = False
    snmp_community: str = "public"
    snmp_index: int = 1
    lpr_queue: str = ""
    lpr_byte_counting: bool = False
    duplex_mode: str = "No consultado"

    @property
    def address(self) -> str:
        return f"{self.host}:{self.port_number}" if self.host else self.port_name

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Job:
    id: int
    status: str = ""


def classify(type_: str, port_name: str, driver: str, host: str) -> str:
    """Decide el tipo de conexion. Mismo criterio que usa la interfaz y el helper."""
    if str(type_).lower() == "connection":
        return "Compartida"
    if re.match(r"^(PORTPROMPT:|nul:|SHRFAX:|FILE:|XPSPort:|Microsoft\.Office)", port_name or "", re.I) or \
            re.search(r"Print To PDF|XPS Document Writer|OneNote|Fax", driver or "", re.I):
        return "Virtual"
    if host:
        return "TCPIP"
    if re.match(r"^WSD", port_name or "", re.I):
        return "WSD"
    if re.match(r"^(USB|TMUSB|DOT4|BTH)", port_name or "", re.I) or re.search(r"TMUSB", port_name or "", re.I):
        return "USB"
    return "Otro"
