"""Registro de operaciones en CSV (exportable a TXT). No guarda contenido de documentos."""
from __future__ import annotations

import csv
import os
import socket
from datetime import datetime
from pathlib import Path

FIELDS = ["FechaHora", "Equipo", "Usuario", "Impresora", "IP", "Controlador",
          "Operacion", "Resultado", "FaseError", "DuracionSeg", "Mensaje"]


def log_file(logs_dir: Path) -> Path:
    return Path(logs_dir) / "operaciones.csv"


def write(logs_dir: Path, *, printer="", host="", driver="", operation="", result="",
          phase=0, seconds=0.0, message="", user="") -> None:
    try:
        f = log_file(logs_dir)
        f.parent.mkdir(parents=True, exist_ok=True)
        new = not f.exists()
        with open(f, "a", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=FIELDS)
            if new:
                w.writeheader()
            w.writerow({"FechaHora": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        "Equipo": os.environ.get("COMPUTERNAME", socket.gethostname()), "Usuario": user,
                        "Impresora": printer, "IP": host, "Controlador": driver, "Operacion": operation,
                        "Resultado": result, "FaseError": phase, "DuracionSeg": round(seconds, 1),
                        "Mensaje": message})
    except OSError:
        pass  # el registro nunca debe romper la operacion


def export(logs_dir: Path, dest_dir: Path) -> tuple[Path, Path]:
    src = log_file(logs_dir)
    if not src.exists():
        raise FileNotFoundError("Aun no hay operaciones registradas.")
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out_csv = Path(dest_dir) / f"DocPrinterTI-registro-{stamp}.csv"
    out_txt = Path(dest_dir) / f"DocPrinterTI-registro-{stamp}.txt"
    out_csv.write_bytes(src.read_bytes())
    with open(src, newline="", encoding="utf-8-sig") as fh, open(out_txt, "w", encoding="utf-8") as tx:
        for r in csv.DictReader(fh):
            tx.write(" | ".join([r["FechaHora"], r["Equipo"], r["Usuario"], r["Impresora"], r["IP"], r["Controlador"],
                                 r["Operacion"], r["Resultado"], f"fase {r['FaseError']}", f"{r['DuracionSeg']}s",
                                 r["Mensaje"]]) + "\n")
    return out_csv, out_txt
