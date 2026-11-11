from docprinter import workflow
from docprinter.backend_base import BackendError
from docprinter.models import Job, classify

from conftest import no_sleep

NAME = "HP LaserJet Contabilidad"


def run(fake, name=NAME, **kw):
    return workflow.reinstall(fake, name, sleep=no_sleep, **kw)


def test_classify():
    assert classify("Connection", r"\\srv\q", "x", "") == "Compartida"
    assert classify("Local", "PORTPROMPT:", "Microsoft Print To PDF", "") == "Virtual"
    assert classify("Local", "IP_1.2.3.4", "HP", "1.2.3.4") == "TCPIP"
    assert classify("Local", "USB001", "Brother", "") == "USB"
    assert classify("Local", "TMUSB001", "EPSON Receipt", "") == "USB"
    assert classify("Local", "WSD-1234", "HP", "") == "WSD"


def test_reinstall_ok_tcp_rebuilds_port_and_keeps_identity(fake):
    before = fake.get_printer(NAME)
    res = run(fake)
    assert res.state == "done", res.log
    assert res.message == "IMPRESORA REINSTALADA CORRECTAMENTE"
    after = fake.get_printer(NAME)
    assert (after.name, after.driver, after.port_name, after.host) == (before.name, before.driver, before.port_name, before.host)
    muts = [m[0] for m in fake.mutations()]
    for m in ("remove_printer", "remove_port", "add_port", "add_printer", "set_ticket"):
        assert m in muts
    assert muts.index("remove_printer") < muts.index("remove_port") < muts.index("add_port") < muts.index("add_printer")


def test_duplex_restored_from_ticket(fake):
    res = run(fake)
    assert res.state == "done"
    assert "TwoSided" in fake.tickets[NAME]
    assert workflow.has_duplex(fake.duplex_caps(NAME))


def test_duplex_lost_gives_warning(fake):
    fake.drop_duplex_after_reinstall = True
    res = run(fake)
    assert res.state == "warning"
    assert any("duplex" in w.lower() for w in res.warnings)


def test_other_printers_untouched(fake):
    others_before = {n: p.to_dict() for n, p in fake.printers.items() if n != NAME}
    run(fake)
    others_after = {n: p.to_dict() for n, p in fake.printers.items() if n != NAME}
    assert others_before == others_after
    assert all(c[1] == NAME for c in fake.mutations() if c[0] in ("remove_printer", "add_printer", "remove_job"))


def test_only_this_printer_jobs_removed(fake):
    fake.jobs[NAME] = [Job(1), Job(2)]
    fake.jobs["Ricoh Sistemas"] = [Job(9)]
    run(fake)
    assert fake.jobs["Ricoh Sistemas"] == [Job(9)]
    assert not any(c[0] == "remove_job" and c[1] != NAME for c in fake.calls)


def test_stuck_jobs_restart_spooler(fake):
    fake.jobs[NAME] = [Job(1)]
    fake.stuck.add(NAME)
    res = run(fake)
    assert res.state == "done"
    assert ("restart_spooler",) in fake.calls


def test_shared_port_is_kept(fake):
    fake.add_demo_printer("Otra en misma IP", "HP Universal Printing PCL 6", host="10.0.0.21")
    res = run(fake)
    assert res.state == "done"
    assert not any(c[0] in ("remove_port", "add_port") for c in fake.calls)


def test_unreachable_host_aborts_before_any_change(fake):
    res = run(fake, "Epson Apagada")
    assert res.state == "error" and res.failed_phase == 2
    assert fake.mutations() == []
    assert "Epson Apagada" in fake.printers


def test_missing_driver_aborts_before_any_change(fake):
    fake.drivers.discard("HP Universal Printing PCL 6")
    res = run(fake)
    assert res.state == "error" and res.failed_phase == 2
    assert fake.mutations() == []


def test_shared_server_printer_not_modified(fake):
    res = run(fake, "Canon Servidor")
    assert res.state == "error" and res.failed_phase == 2
    assert fake.mutations() == []


def test_nonexistent_printer(fake):
    res = run(fake, "No existe")
    assert res.state == "error" and res.failed_phase == 1


def test_simulate_changes_nothing(fake):
    res = run(fake, simulate=True)
    assert res.state == "done" and "SIMULACION" in res.message
    assert fake.mutations() == []


def test_failure_on_add_printer_rolls_back(fake):
    before = fake.get_printer(NAME)
    fake.fail["add_printer"] = BackendError("boom")   # falla solo la 1ra vez; el rollback tiene exito
    res = run(fake)
    assert res.state == "rolledback" and res.failed_phase == 6
    assert res.user_action
    after = fake.get_printer(NAME)
    assert (after.driver, after.port_name) == (before.driver, before.port_name)
    assert fake.port_exists(before.port_name)


def test_failure_on_add_port_restores_port_and_printer(fake):
    fake.fail["add_port"] = BackendError("boom")
    res = run(fake)
    assert res.state == "rolledback" and res.failed_phase == 5
    assert NAME in fake.printers and fake.port_exists("IP_10.0.0.21")


def test_rollback_failure_is_reported(fake):
    orig = fake.add_printer

    def always_fail(p):
        fake.calls.append(("add_printer", p.name))
        raise BackendError("boom")
    fake.add_printer = always_fail
    res = run(fake)
    assert res.state == "error"
    assert any("No se pudo restaurar" in l for l in res.log)


def test_usb_printer_reuses_port(fake):
    res = run(fake, "Brother Recepcion")
    assert res.state == "done", res.log
    assert not any(c[0] in ("remove_port", "add_port") for c in fake.calls)


def test_progress_callback_and_oplog(fake):
    updates, logged = [], []
    res = run(fake, on_update=lambda r: updates.append(r.phase), oplog=lambda **kw: logged.append(kw))
    assert max(updates) == 8 and res.state == "done"
    assert logged and logged[0]["operation"] == "Reinstalacion" and logged[0]["result"] == "OK"


def test_diagnose_unreachable(fake):
    lines, concl = workflow.diagnose(fake, "Epson Apagada")
    assert "no responde" in concl
    assert any("[FALLO]" in l for l in lines)


def test_diagnose_healthy(fake):
    _, concl = workflow.diagnose(fake, NAME)
    assert "no detecta fallas" in concl


def test_diagnose_consumable_status(fake):
    fake.printers[NAME].status = "TonerLow"
    lines, concl = workflow.diagnose(fake, NAME)
    assert any("[AVISO]" in l and "TonerLow" in l for l in lines)
    assert not any("[FALLO]" in l and "TonerLow" in l for l in lines)
    assert "Revisión física" in concl or "revisión física" in concl or "TonerLow" in concl


def test_report_r02_generation(fake, tmp_path):
    from docprinter.report_r02 import generate_r02, save_r02_report
    p = fake.get_printer(NAME)
    content = generate_r02(
        p,
        que_se_hizo="- Diagnostico y limpieza de cola.",
        estado_equipo="Operativo",
        comentario_finalizacion="Servicio completado conforme.",
        material_utilizado="NINGUNO",
        tipo_servicio="IMPRESORA",
    )
    assert "FORMULARIO R-02" in content
    assert "TIPO DE SERVICIO     : IMPRESORA" in content
    assert "MATERIAL UTILIZADO   : NINGUNO" in content
    assert "ESTADO DEL EQUIPO    : Operativo" in content
    assert "QUE SE HIZO:" in content
    assert "COMENTARIO DE FINALIZACION:" in content
    assert "CONFORMIDAD" not in content

    out_file, saved_content = save_r02_report(p, dest_dir=tmp_path)
    assert out_file.exists()
    assert "FORMULARIO R-02" in out_file.read_text(encoding="utf-8")
