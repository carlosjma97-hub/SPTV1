import subprocess
import sys
from types import SimpleNamespace
from xml.etree import ElementTree as ET

from docprinter import admin_setup, backend_windows
from docprinter.models import PrinterInfo


def test_task_xml_is_valid_and_runs_as_system():
    x = admin_setup.task_xml(r"C:\Program Files\DocPrinterTI\DocPrinterTI.exe", "helper", r"C:\Program Files\DocPrinterTI")
    root = ET.fromstring(x.split("?>", 1)[1])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    assert root.find("t:Principals/t:Principal/t:UserId", ns).text == "S-1-5-18"
    assert root.find("t:Actions/t:Exec/t:Command", ns).text.endswith("DocPrinterTI.exe")


def test_acl_commands_use_sids(dirs):
    cmds = admin_setup.acl_commands(dirs)
    assert len(cmds) == 5
    assert all("*S-1-5-18:(OI)(CI)F" in c and "*S-1-5-32-544:(OI)(CI)F" in c for c in cmds)
    queue_cmd = next(c for c in cmds if c[1].endswith("queue"))
    assert "*S-1-5-32-545:(OI)(CI)M" in queue_cmd
    backups_cmd = next(c for c in cmds if c[1].endswith("backups"))
    assert not any("S-1-5-32-545" in a for a in backups_cmd)


def fake_runner(calls, fail_on=None):
    def run(cmd, **kw):
        calls.append(cmd)
        rc = 1 if fail_on and cmd[0] == fail_on[0] and cmd[1] == fail_on[1] else 0
        return SimpleNamespace(returncode=rc, stdout="", stderr="simulado")
    return run


def test_install_runs_expected_commands(dirs):
    calls = []
    dirs.heartbeat.write_text("x")   # simula helper activo
    assert admin_setup.install(dirs, run=fake_runner(calls), wait_seconds=2) == 0
    names = [c[0] + " " + (c[1] if c[0] == "schtasks" else "") for c in calls]
    assert names.count("icacls ") == 5
    assert "schtasks /Create" in names and "schtasks /Run" in names


def test_install_failure_returns_1(dirs):
    assert admin_setup.install(dirs, run=fake_runner([], fail_on=("schtasks", "/Create")), wait_seconds=1) == 1


def test_uninstall_keeps_logs(dirs):
    (dirs.logs / "operaciones.csv").write_text("x")
    admin_setup.uninstall(keep_logs=True, dirs=dirs, run=fake_runner([]))
    assert (dirs.logs / "operaciones.csv").exists() and not dirs.queue.exists()
    admin_setup.uninstall(keep_logs=False, dirs=dirs, run=fake_runner([]))
    assert not dirs.root.exists()


def test_run_ps_builds_encoded_command_and_params(monkeypatch):
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["env"] = cmd, kw["env"]
        seen["params"] = open(kw["env"]["DPTI_PARAMS_FILE"], encoding="utf-8").read()
        return SimpleNamespace(returncode=0, stdout=b"[]", stderr=b"")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert backend_windows.run_ps("1", {"name": "Impresora \"rara\"; calc.exe"}) == "[]"
    assert "-EncodedCommand" in seen["cmd"] and "-NoProfile" in seen["cmd"]
    assert "calc.exe" in seen["params"]                    # viaja como DATO dentro del JSON
    import base64
    script = base64.b64decode(seen["cmd"][-1]).decode("utf-16-le")
    assert "calc.exe" not in script                        # nunca dentro del texto del script


def test_windows_backend_parses_printer_rows(monkeypatch):
    rows = [{"name": "HP", "driver": "HP PCL", "driver_found": True, "manufacturer": "HP", "port_name": "IP_1.2.3.4",
             "port_found": True, "type": "Local", "status": "Normal", "shared": False, "share_name": "", "location": "",
             "comment": "", "host": "1.2.3.4", "number": 9100, "protocol": "1", "snmp": True, "community": "public",
             "index": 1, "lpr_queue": "", "lpr_bc": False}]
    import json
    monkeypatch.setattr(backend_windows, "run_ps", lambda s, p=None, timeout=120: json.dumps(rows))
    p = backend_windows.WindowsBackend().list_printers()[0]
    assert (p.kind, p.protocol, p.host, p.port_number, p.snmp) == ("TCPIP", "RAW", "1.2.3.4", 9100, True)


def test_check_host_rejects_dangerous_host():
    assert backend_windows.WindowsBackend().check_host("-n 5 & calc", 9100) == (False, False)
