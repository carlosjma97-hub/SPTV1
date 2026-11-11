"""Generador de Reporte de Servicio Tecnico - FORMULARIO R-02."""
from __future__ import annotations

import os
import socket
from datetime import datetime
from pathlib import Path
from typing import Optional

from .models import PrinterInfo
from .paths import get_desktop_dir


def generate_r02(
    printer: PrinterInfo,
    *,
    que_se_hizo: str = "",
    estado_equipo: str = "",
    comentario_finalizacion: str = "",
    material_utilizado: str = "NINGUNO",
    tipo_servicio: str = "IMPRESORA",
    tecnico: str = "Soporte Tecnico TI",
    usuario: str = "",
    equipo: str = "",
    acciones_detalle: Optional[list[str]] = None,
) -> str:
    now = datetime.now()
    fecha_hora = now.strftime("%Y-%m-%d %H:%M:%S")
    num_reporte = f"R02-{now.strftime('%Y%m%d-%H%M%S')}"
    equipo_nombre = equipo or os.environ.get("COMPUTERNAME", socket.gethostname())
    usuario_nombre = usuario or os.environ.get("USERNAME", "Funcionario")

    if not estado_equipo:
        if printer.status == "Normal":
            estado_equipo = "Operativo (Windows: Normal)"
        else:
            estado_equipo = f"Atencion requerida: {printer.status}"

    if not que_se_hizo:
        if acciones_detalle:
            que_se_hizo = "\n".join(f"  - {act}" for act in acciones_detalle)
        else:
            que_se_hizo = (
                "  - Diagnostico integral de cola y comunicacion con la impresora.\n"
                "  - Cancelacion y purga de trabajos bloqueados en el Spooler.\n"
                "  - Verificacion de resolucion del puerto de conexion y enlace de red/USB.\n"
                "  - Comprobacion de controlador existente y restauracion de configuracion duplex."
            )

    if not comentario_finalizacion:
        comentario_finalizacion = (
            "Servicio de soporte tecnico concluido exitosamente.\n"
            "La impresora quedo operativa y reconocida por el sistema operativo.\n"
            "Se realizo comprobacion de conexion. Verifique la impresion fisica mediante pagina de prueba."
        )

    sep = "=" * 70
    sub_sep = "-" * 70

    report = f"""{sep}
DATOS PARA FINALIZACION DE SOPORTE - FORMULARIO R-02
{sep}
FECHA Y HORA         : {fecha_hora}
EQUIPO (HOST)        : {equipo_nombre}
USUARIO SOLICITANTE  : {usuario_nombre}
IMPRESORA            : {printer.name}
TIPO Y DIRECCION     : {printer.kind} | {printer.address}
CONTROLADOR          : {printer.driver}
{sub_sep}
FORMULARIO           : R-02
TIPO DE SERVICIO     : {tipo_servicio}
ESTADO DEL EQUIPO    : {estado_equipo}
MATERIAL UTILIZADO   : {material_utilizado}
{sub_sep}
QUE SE HIZO:
{que_se_hizo}
{sub_sep}
COMENTARIO DE FINALIZACION:
{comentario_finalizacion}
{sep}
"""
    return report


def save_r02_report(
    printer: PrinterInfo,
    dest_dir: Optional[Path] = None,
    **kwargs
) -> tuple[Path, str]:
    content = generate_r02(printer, **kwargs)
    out_dir = Path(dest_dir) if dest_dir else get_desktop_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    safe_name = "".join(c if c.isalnum() or c in "._-" else "_" for c in printer.name)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_file = out_dir / f"DocPrinterTI-Formulario-R02-{safe_name}-{stamp}.txt"
    out_file.write_text(content, encoding="utf-8")
    return out_file, content
