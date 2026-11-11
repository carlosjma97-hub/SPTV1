import json

import pytest

from docprinter import helper, ipc, oplog

from conftest import no_sleep

NAME = "HP LaserJet Contabilidad"
GOOD_ID = "123e4567-e89b-12d3-a456-426614174000"


def write_req(dirs, rid, data):
    p = dirs.queue / f"{rid}.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_submit_and_parse_roundtrip(dirs):
    rid = ipc.submit(dirs, NAME, "Reinstall")
    req = ipc.parse_request(dirs.queue / f"{rid}.json")
    assert (req.id, req.operation, req.printer) == (rid, "Reinstall", NAME)


@pytest.mark.parametrize("data", [
    {"id": GOOD_ID, "operation": "Format", "printerName": NAME},                 # operacion no permitida
    {"id": GOOD_ID, "operation": "Reinstall", "printerName": "x" * 201},         # nombre largo
    {"id": GOOD_ID, "operation": "Reinstall", "printerName": "a\x00b"},          # caracter de control
    {"id": "otro-id", "operation": "Reinstall", "printerName": NAME},            # id no coincide
    {"id": GOOD_ID, "operation": "Reinstall"},                                   # falta impresora
    ["no", "es", "dict"],
])
def test_parse_rejects_bad_requests(dirs, data):
    with pytest.raises(ValueError):
        ipc.parse_request(write_req(dirs, GOOD_ID, data))


def test_parse_rejects_bad_filename(dirs):
    p = write_req(dirs, "no-es-uuid", {"id": "no-es-uuid", "operation": "Reinstall", "printerName": NAME})
    with pytest.raises(ValueError):
        ipc.parse_request(p)


def test_helper_processes_valid_request(fake, dirs):
    rid = ipc.submit(dirs, NAME, "Reinstall")
    assert helper.process_queue_once(fake, dirs, no_sleep) == 1
    res = ipc.read_result(dirs, rid)
    assert res["state"] == "done" and res["phase"] == 8
    assert not (dirs.queue / f"{rid}.json").exists()      # solicitud consumida
    assert dirs.heartbeat.exists()
    assert list(dirs.backups.glob("*.json"))              # respaldo guardado
    assert "Reinstalacion" in oplog.log_file(dirs.logs).read_text(encoding="utf-8-sig")


def test_helper_rejects_unknown_printer(fake, dirs):
    rid = ipc.submit(dirs, "Impresora Inventada", "Reinstall")
    helper.process_queue_once(fake, dirs, no_sleep)
    res = ipc.read_result(dirs, rid)
    assert res["state"] == "error" and "ya no esta instalada" in res["message"]
    assert fake.mutations() == []


def test_helper_rejects_forbidden_operation(fake, dirs):
    write_req(dirs, GOOD_ID, {"id": GOOD_ID, "operation": "RunCommand", "printerName": NAME})
    helper.process_queue_once(fake, dirs, no_sleep)
    assert ipc.read_result(dirs, GOOD_ID)["state"] == "error"
    assert fake.mutations() == []


def test_helper_simulate(fake, dirs):
    rid = ipc.submit(dirs, NAME, "Simulate")
    helper.process_queue_once(fake, dirs, no_sleep)
    assert ipc.read_result(dirs, rid)["state"] == "done"
    assert fake.mutations() == []


def test_export_log(fake, dirs, tmp_path):
    ipc.submit(dirs, NAME, "Reinstall")
    helper.process_queue_once(fake, dirs, no_sleep)
    out = tmp_path / "out"
    out.mkdir()
    c, t = oplog.export(dirs.logs, out)
    assert c.exists() and "Reinstalacion" in t.read_text(encoding="utf-8")


def test_helper_remove_printer(fake, dirs):
    rid = ipc.submit(dirs, NAME, "Remove")
    helper.process_queue_once(fake, dirs, no_sleep)
    res = ipc.read_result(dirs, rid)
    assert res["state"] == "done"
    assert NAME not in fake.printers
    assert "Eliminar" in oplog.log_file(dirs.logs).read_text(encoding="utf-8-sig")


def test_helper_rename_printer(fake, dirs):
    new_name = "FINANZAS-CONT-IMP01 (HP 4001 BN)"
    rid = ipc.submit(dirs, NAME, "Rename", new_name=new_name)
    helper.process_queue_once(fake, dirs, no_sleep)
    res = ipc.read_result(dirs, rid)
    assert res["state"] == "done"
    assert NAME not in fake.printers
    assert new_name in fake.printers
    assert "Renombrar" in oplog.log_file(dirs.logs).read_text(encoding="utf-8-sig")


def test_naming_codification():
    from docprinter.naming import build_printer_name, clean_model_name, detect_is_color

    # Limpieza de modelos
    clean = clean_model_name("HP LaserJet Pro 4001 4002 4003 4004 PCL-6 (V4)")
    assert "PCL" not in clean and "4001" in clean
    assert detect_is_color("HP Color LaserJet Pro MFP M477 PCL 6")
    assert not detect_is_color("HP LaserJet P4014")

    # Reglas de codificacion
    name_std = build_printer_name("Finanzas", "Contabilidad", "1", "HP M4001", False, estilo="estandar")
    assert name_std == "FINANZAS-CONTABILIDAD-IMP01 (HP M4001 BN)"

    name_short = build_printer_name("Finanzas", "Contabilidad", "2", "HP M4001", True, estilo="corto")
    assert name_short == "FINANZAS_CONTABILIDAD_IMP02"

    name_class = build_printer_name("Administracion", "RRHH", 3, "Brother", False, estilo="clasico")
    assert name_class == "ADMINISTRACION - RRHH - IMP 03 (Brother)"
