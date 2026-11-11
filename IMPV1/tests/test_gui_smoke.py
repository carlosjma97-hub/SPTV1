"""Prueba de humo de la interfaz con impresoras simuladas. Se omite si no hay pantalla (Linux sin DISPLAY)."""
import os
import threading
import time
from pathlib import Path
from tkinter import messagebox

import pytest

pytestmark = pytest.mark.skipif(os.name != "nt" and not os.environ.get("DISPLAY"), reason="sin pantalla")


def wait_until(app, cond, timeout=15):
    end = time.time() + timeout
    while time.time() < end:
        app.update()
        if cond():
            return True
        time.sleep(0.05)
    return False


def test_gui_reinstall_flow(tmp_path, monkeypatch):
    from docprinter import helper
    from docprinter.backend_fake import FakeBackend
    from docprinter.gui import App
    from docprinter.paths import get_dirs
    b = FakeBackend.demo()
    dirs = get_dirs(tmp_path / "d").ensure()
    stop = threading.Event()
    threading.Thread(target=helper.run_loop, args=(b, dirs, stop, 0.2, lambda s: None), daemon=True).start()
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: True)
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    app = App(b, dirs, "TEST")
    try:
        assert wait_until(app, lambda: len(app.tree.get_children()) == 5)
        assert wait_until(app, lambda: app.service_ok)
        app.tree.selection_set("p0")           # HP LaserJet Contabilidad
        app.update()
        assert app.selected().name == "HP LaserJet Contabilidad"
        app.reinstall()
        assert wait_until(app, lambda: app.banner.cget("text") == "IMPRESORA REINSTALADA CORRECTAMENTE")
        app.tree.selection_set("p4")           # Epson apagada -> error controlado
        app.update()
        assert wait_until(app, lambda: str(app.buttons["reinstall"].cget("state")) != "disabled")
        app.reinstall()
        assert wait_until(app, lambda: app.banner.cget("text").startswith("NO SE PUDO REINSTALAR (fase 2)"))
        assert wait_until(app, lambda: str(app.buttons["diag"].cget("state")) != "disabled" and app.selected() is not None)
        app.diagnose()
        assert wait_until(app, lambda: "CONCLUSION" in app.log.get("1.0", "end"))
    finally:
        stop.set()
        app.destroy()
