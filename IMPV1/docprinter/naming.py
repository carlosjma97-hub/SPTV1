"""Reglas de codificacion y nomenclatura institucional para impresoras."""
from __future__ import annotations

import re
from typing import Optional

from .models import PrinterInfo


def clean_model_name(driver: str, name: str = "") -> str:
    """Extrae un modelo limpio y legible a partir del controlador o nombre original."""
    text = driver or name or "Generica"
    # Quitar sufijos tecnicos de controladores de Windows
    text = re.sub(r"\s*(PCL[- ]?6|PCL[- ]?5|PS|PostScript|Class Driver|Printer Driver|Driver|\(V4\)|\(V3\)|\(Red\)|Series)\b", "", text, flags=re.I)
    # Quitar rangos largos como "4001 4002 4003 4004" dejando el primero
    text = re.sub(r"(\b\d{3,4}\b)(?:\s+\d{3,4})+", r"\1", text)
    # Quitar resoluciones tecnicas como "(203dpi)"
    text = re.sub(r"\s*\(\d+dpi\)", "", text, flags=re.I)
    # Quitar barras de modelos combinados "P4014/P4015" -> "P4014"
    text = re.sub(r"/.*", "", text)
    # Normalizar espacios
    text = re.sub(r"\s+", " ", text).strip()
    return text if text else "Impresora"


def detect_is_color(driver: str, name: str = "") -> bool:
    """Detecta automaticamente si el equipo es a color."""
    target = f"{driver} {name}".lower()
    return "color" in target or "clj" in target


def format_printer_number(num: str | int) -> str:
    """Formatea el numero a 2 digitos (ej. 1 -> '01')."""
    try:
        n = int(str(num).strip())
        return f"{n:02d}"
    except ValueError:
        return str(num).strip() or "01"


def sanitize_printer_name(name: str) -> str:
    """Elimina caracteres prohibidos por Windows en nombres de impresoras."""
    # Windows no admite en nombres de impresora: \ / , ! o caracteres de control
    s = re.sub(r'[\x00-\x1f\\/,!]', '', name)
    s = re.sub(r'\s+', ' ', s)
    return s.strip()[:200]


def build_printer_name(
    area: str,
    unidad: str,
    numero: str | int,
    modelo: str,
    es_color: bool,
    estilo: str = "estandar",
) -> str:
    """
    Construye el nombre codificado segun las reglas institucionales:
    - estandar: [AREA]-[UNIDAD]-IMP[01] ([MODELO] [Color/BN])
    - corto:    [AREA]_[UNIDAD]_IMP[01]
    - clasico:  [AREA] - [UNIDAD] - IMP [01] ([MODELO])
    """
    a = area.strip().upper() or "AREA"
    u = unidad.strip().upper() or "UNIDAD"
    n = format_printer_number(numero)
    m = modelo.strip() or "IMP"
    tipo_color = "Color" if es_color else "BN"

    if estilo == "corto":
        # Formato compacto codificado
        res = f"{a}_{u}_IMP{n}"
    elif estilo == "clasico":
        # Formato clasico descriptivo
        res = f"{a} - {u} - IMP {n} ({m})"
    else:
        # Formato estandar institucional (mas claro y ordenado)
        res = f"{a}-{u}-IMP{n} ({m} {tipo_color})"

    return sanitize_printer_name(res)


def suggest_naming_for_printer(p: PrinterInfo) -> dict:
    """Prepara sugerencias de codificacion a partir de una impresora existente."""
    modelo = clean_model_name(p.driver, p.name)
    es_color = detect_is_color(p.driver, p.name)
    
    # Intentar adivinar si ya tenia area o unidad
    area_sugerida = ""
    unidad_sugerida = ""
    num_sugerido = "01"
    
    parts = re.split(r"[-_ ]+", p.name)
    if len(parts) >= 2 and parts[0].isalpha():
        area_sugerida = parts[0].upper()
    if len(parts) >= 3 and parts[1].isalpha():
        unidad_sugerida = parts[1].upper()

    return {
        "area": area_sugerida,
        "unidad": unidad_sugerida,
        "numero": num_sugerido,
        "modelo": modelo,
        "es_color": es_color,
    }
