"""Interfaz Tkinter (solo biblioteca estandar). Corre como usuario normal; las acciones administrativas
se piden al helper mediante la cola. Las llamadas lentas van a hilos para no congelar la ventana."""
from __future__ import annotations

import queue
import tempfile
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

from . import ipc, oplog, workflow
from .backend_base import Backend
from .models import SUPPORTED_KINDS, PrinterInfo
from .naming import (
    build_printer_name,
    clean_model_name,
    detect_is_color,
    sanitize_printer_name,
    suggest_naming_for_printer,
)
from .paths import Dirs, get_desktop_dir, get_dirs
from .report_r02 import save_r02_report

APP_NAME = "DocPrinter TI"
BLUE, GREEN, RED, AMBER = "#1F3A5F", "#2E7D32", "#B71C1C", "#B26A00"
FINAL_STATES = ("done", "warning", "error", "rolledback")
KIND_LABEL = {"TCPIP": "TCP/IP", "USB": "USB", "Compartida": "Compartida", "Virtual": "Virtual", "WSD": "WSD"}


class App(tk.Tk):
    def __init__(self, backend: Backend, dirs: Dirs, institution: str, fake: bool = False):
        super().__init__()
        self.b, self.dirs, self.fake = backend, dirs, fake
        self.printers: dict[str, PrinterInfo] = {}
        self.iid_to_name: dict[str, str] = {}
        self.q: queue.Queue = queue.Queue()
        self.active_id: str | None = None
        self.sent_at = 0.0
        self.pending: dict | None = None
        self.last_res: dict | None = None
        self.last_diagnose: tuple[list[str], str] | None = None
        self.last_target_printer: str = ""
        self.service_ok = False
        self.title(APP_NAME)
        self.geometry("1120x780")
        self.minsize(960, 680)
        self._build(institution)
        self.after(100, self._pump)
        self.after(1000, self._heartbeat)
        self.refresh()

    # ------------------------------------------------------------------ interfaz
    def _build(self, institution: str) -> None:
        head = tk.Frame(self, bg=BLUE)
        head.pack(fill="x")
        tk.Label(head, text=APP_NAME, fg="white", bg=BLUE, font=("Segoe UI", 22, "bold")).pack(side="left", padx=16, pady=(10, 0))
        tk.Label(head, text=institution, fg="#C9D6E8", bg=BLUE, font=("Segoe UI", 10)).pack(side="left", padx=4, pady=(22, 0))
        self.svc = tk.Label(head, text="Servicio: verificando...", fg="white", bg=BLUE)
        self.svc.pack(side="right", padx=16)

        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, padx=14, pady=10)
        cols = ("name", "manu", "addr", "driver", "status", "conn")
        self.tree = ttk.Treeview(mid, columns=cols, show="headings", selectmode="browse")
        for c, t, w in (("name", "Impresora", 220), ("manu", "Fabricante", 110), ("addr", "IP / Puerto", 130),
                        ("driver", "Controlador", 220), ("status", "Estado", 70), ("conn", "Conexion", 85)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor="w")
        self.tree.pack(side="left", fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
        side = ttk.LabelFrame(mid, text=" Impresora seleccionada ")
        side.pack(side="left", fill="y", padx=(10, 0))
        self.detail = tk.Label(side, text="Seleccione una impresora.", justify="left", anchor="nw", wraplength=300, width=38)
        self.detail.pack(fill="both", expand=True, padx=8, pady=8)

        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=14, pady=(0, 4))
        bar1 = ttk.Frame(bar)
        bar1.pack(fill="x", pady=(0, 4))
        bar2 = ttk.Frame(bar)
        bar2.pack(fill="x")

        self.buttons = {}
        for key, text, cmd in (("reinstall", "REINSTALAR IMPRESORA", self.reinstall),
                               ("rename", "RENOMBRAR (CODIFICAR)", self.rename_printer_gui),
                               ("remove", "ELIMINAR IMPRESORA", self.remove_printer_gui),
                               ("refresh", "ACTUALIZAR LISTA", self.refresh)):
            b = ttk.Button(bar1, text=text, command=cmd)
            b.pack(side="left", padx=(0, 8), ipady=5)
            self.buttons[key] = b

        self.sim = tk.BooleanVar(value=False)
        ttk.Checkbutton(bar1, text="Modo simulacion (no modifica nada)", variable=self.sim).pack(side="left", padx=8)

        for key, text, cmd in (("diag", "DIAGNOSTICAR IMPRESORA", self.diagnose),
                               ("test", "IMPRIMIR PAGINA DE PRUEBA", self.test_page),
                               ("r02", "REPORTE FORMULARIO R-02", self.generate_r02),
                               ("export", "EXPORTAR REGISTRO", self.export_log)):
            b = ttk.Button(bar2, text=text, command=cmd)
            b.pack(side="left", padx=(0, 8), ipady=4)
            self.buttons[key] = b

        box = ttk.LabelFrame(self, text=" Progreso ")
        box.pack(fill="both", padx=14, pady=10)
        self.banner = tk.Label(box, text="Listo.", font=("Segoe UI", 14, "bold"), anchor="w", justify="left", wraplength=1000)
        self.banner.pack(fill="x", padx=8, pady=(6, 0))
        self.phase = tk.Label(box, text="", anchor="w", justify="left", wraplength=1000, fg="#444")
        self.phase.pack(fill="x", padx=8)
        self.pb = ttk.Progressbar(box, maximum=workflow.TOTAL_PHASES)
        self.pb.pack(fill="x", padx=8, pady=4)
        self.log = tk.Text(box, height=9, state="disabled", font=("Consolas", 9), wrap="word")
        self.log.pack(fill="both", padx=8, pady=(0, 8))

    # ------------------------------------------------------------------ utilidades
    def run_bg(self, fn, done) -> None:
        def worker():
            try:
                self.q.put((done, fn(), None))
            except Exception as e:  # noqa: BLE001
                self.q.put((done, None, e))
        threading.Thread(target=worker, daemon=True).start()

    def _pump(self) -> None:
        try:
            while True:
                done, res, err = self.q.get_nowait()
                done(res, err)
        except queue.Empty:
            pass
        self.after(100, self._pump)

    def set_busy(self, busy: bool) -> None:
        for b in self.buttons.values():
            b.state(["disabled"] if busy else ["!disabled"])
        self.tree.configure(selectmode="none" if busy else "browse")

    def set_banner(self, text: str, color: str = "black") -> None:
        self.banner.config(text=text, fg=color)

    def set_log(self, lines) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.insert("end", "\n".join(lines))
        self.log.see("end")
        self.log.config(state="disabled")

    def selected(self) -> PrinterInfo | None:
        sel = self.tree.selection()
        return self.printers.get(self.iid_to_name.get(sel[0])) if sel else None

    def _heartbeat(self) -> None:
        try:
            age = time.time() - self.dirs.heartbeat.stat().st_mtime
        except OSError:
            age = 9999
        self.service_ok = age < 60
        self.svc.config(text="Servicio administrativo: " + ("ACTIVO" if self.service_ok else "NO RESPONDE"),
                        fg="#7CFC00" if self.service_ok else "#FF6B6B")
        self.after(5000, self._heartbeat)

    # ------------------------------------------------------------------ lista y detalle
    def refresh(self) -> None:
        cur = self.selected()
        self._keep = cur.name if cur else None   # conservar la seleccion tras actualizar
        self.set_busy(True)
        self.run_bg(self.b.list_printers, self._on_list)

    def _on_list(self, printers, err) -> None:
        self.set_busy(False)
        if err:
            messagebox.showerror(APP_NAME, f"No se pudo leer la lista de impresoras:\n{err}")
            return
        self.tree.delete(*self.tree.get_children())
        self.printers, self.iid_to_name = {}, {}
        for i, p in enumerate(printers):
            iid = f"p{i}"
            self.printers[p.name] = p
            self.iid_to_name[iid] = p.name
            self.tree.insert("", "end", iid=iid, values=(p.name, p.manufacturer, p.address, p.driver, p.status,
                                                          KIND_LABEL.get(p.kind, "Otra")))
        self.detail.config(text="Seleccione una impresora.")
        for iid, n in self.iid_to_name.items():
            if n == getattr(self, "_keep", None):
                self.tree.selection_set(iid)
                break

    def _on_select(self) -> None:
        p = self.selected()
        if not p:
            return
        self.detail.config(text=self._detail_text(p, "consultando...", p.duplex_mode))
        name = p.name

        def fetch():
            caps = self.b.duplex_caps(name)
            info = self.b.get_printer(name)
            return caps, info.duplex_mode, self.b.default_printer() == name

        def done(res, err):
            cur = self.selected()
            if err or not cur or cur.name != name:
                return
            caps, mode, is_default = res
            txt = "No consultable" if caps is None else ("Admitido por el controlador" if workflow.has_duplex(caps) else "No admitido")
            self.detail.config(text=self._detail_text(cur, txt, mode, is_default))
        self.run_bg(fetch, done)

    @staticmethod
    def _detail_text(p: PrinterInfo, dup: str, mode: str, default: bool = False) -> str:
        t = (f"Nombre: {p.name}\nFabricante: {p.manufacturer}\nControlador: {p.driver}\nIP: {p.host}\n"
             f"Puerto: {p.port_name}" + (f" ({p.port_number})" if p.port_number else "") +
             f"\nProtocolo: {p.protocol}\nEstado (Windows): {p.status}\nConexion: {p.kind}\n"
             f"Duplex: {dup}\nDuplex predeterminado: {mode}")
        return t + ("\nPredeterminada: Si" if default else "")

    # ------------------------------------------------------------------ acciones
    def reinstall(self) -> None:
        p = self.selected()
        if not p:
            return messagebox.showinfo(APP_NAME, "Seleccione primero una impresora de la lista.")
        if not self.service_ok:
            return messagebox.showwarning(APP_NAME, "El componente administrativo no responde. Contacte a la Unidad de Sistemas.")
        if p.kind not in SUPPORTED_KINDS:
            return messagebox.showinfo(APP_NAME, f"Esta impresora es de tipo '{p.kind}' y no puede reinstalarse "
                                       "automaticamente.\nUse DIAGNOSTICAR IMPRESORA y avise a Sistemas.")
        simulate = self.sim.get()
        if not simulate and not messagebox.askyesno(
                APP_NAME, f"Se reinstalara la impresora:\n{p.name}\n\nLos trabajos pendientes de ESTA impresora se "
                "cancelaran. El proceso puede tardar unos minutos.\n\nDesea continuar?", icon="warning"):
            return
        self.set_busy(True)
        self.set_banner("Preparando...", BLUE)
        name = p.name

        def prep():  # datos que solo se pueden leer en el contexto del usuario
            try:
                ticket = self.b.get_ticket(name)
            except Exception:  # noqa: BLE001
                ticket = None
            return {"name": name, "ticket": ticket, "was_default": self.b.default_printer() == name, "sim": simulate}

        def sent(res, err):
            self.pending = res
            self.active_id = ipc.submit(self.dirs, name, "Simulate" if simulate else "Reinstall")
            self.sent_at = time.time()
            self.pb["value"] = 0
            self.set_log([])
            self.set_banner("Procesando... no apague el equipo.", BLUE)
            self.phase.config(text="Solicitud enviada al componente administrativo.")
            self.after(700, self._poll)
        self.run_bg(prep, sent)

    def _poll(self) -> None:
        if not self.active_id:
            return
        res = ipc.read_result(self.dirs, self.active_id)
        if res is None:
            if time.time() - self.sent_at > 30:
                self.active_id = None
                self.set_busy(False)
                self.set_banner("El componente administrativo no respondio.", RED)
                self.phase.config(text="Contacte a la Unidad de Sistemas.")
                return
            self.after(700, self._poll)
            return
        self.pb["value"] = res.get("phase", 0)
        self.phase.config(text=f"[{res.get('phase', 0)}/{res.get('total', 8)}] {res.get('text', '')}")
        self.set_log(res.get("log", []))
        if res.get("state") in FINAL_STATES:
            self._finish(res)
        else:
            self.after(700, self._poll)

    def _finish(self, res: dict) -> None:
        self.active_id = None
        self.last_res = res
        self.last_target_printer = self.pending.get("name") if self.pending else ""
        ok = res["state"] in ("done", "warning")
        if ok:
            self.set_banner(res["message"], AMBER if res["state"] == "warning" else GREEN)
            self.phase.config(text="Windows reconoce la impresora. Para confirmar la impresion fisica use IMPRIMIR PAGINA DE PRUEBA.")
            self.pb["value"] = workflow.TOTAL_PHASES
            pend = self.pending
            if pend and pend.get("op") == "Rename":
                self.phase.config(text=f"Nombre actualizado en Windows a: {pend.get('new_name')}")
                self._keep = pend.get("new_name")
            elif pend and pend.get("op") == "Remove":
                self.phase.config(text="Impresora retirada correctamente del sistema.")
                self._keep = None
            else:
                self.phase.config(text="Windows reconoce la impresora. Para confirmar la impresion fisica use IMPRIMIR PAGINA DE PRUEBA.")
                if pend and not pend.get("sim"):
                    def restore():  # preferencias personales e impresora predeterminada (contexto del usuario)
                        if pend.get("ticket"):
                            try:
                                self.b.set_ticket(pend["name"], pend["ticket"])
                            except Exception:  # noqa: BLE001
                                pass
                        if pend.get("was_default"):
                            self.b.set_default_printer(pend["name"])
                    self.run_bg(restore, lambda r, e: None)
        else:
            self.set_banner(res["message"], RED)
            self.phase.config(text=res.get("user_action", ""))
        self.set_busy(False)
        self.after(500, self.refresh)

    def diagnose(self) -> None:
        p = self.selected()
        if not p:
            return messagebox.showinfo(APP_NAME, "Seleccione primero una impresora de la lista.")
        self.set_busy(True)

        def done(res, err):
            self.set_busy(False)
            if err:
                return messagebox.showerror(APP_NAME, f"No se pudo diagnosticar:\n{err}")
            lines, conclusion = res
            self.last_diagnose = (lines, conclusion)
            self.last_target_printer = p.name
            self.set_log(lines + ["", "CONCLUSION: " + conclusion])
            self.set_banner(f"Diagnostico: {p.name}", BLUE)
            self.phase.config(text="")
        self.run_bg(lambda: workflow.diagnose(self.b, p.name), done)

    def test_page(self) -> None:
        p = self.selected()
        if not p:
            return messagebox.showinfo(APP_NAME, "Seleccione primero una impresora de la lista.")
        self.b.print_test_page(p.name)
        self.set_banner("Pagina de prueba enviada a la cola.", BLUE)
        self.phase.config(text="Windows solo confirma el ENVIO. Verifique que la hoja salga fisicamente de la impresora.")

    def export_log(self) -> None:
        try:
            desk = get_desktop_dir()
            c, t = oplog.export(self.dirs.logs, desk)
            messagebox.showinfo(APP_NAME, f"Registro exportado:\n{c}\n{t}")
        except FileNotFoundError as e:
            messagebox.showinfo(APP_NAME, str(e))
        except OSError as e:
            messagebox.showerror(APP_NAME, f"No se pudo exportar: {e}")

    def remove_printer_gui(self) -> None:
        p = self.selected()
        if not p:
            return messagebox.showinfo(APP_NAME, "Seleccione primero la impresora que desea eliminar.")
        if not self.service_ok:
            return messagebox.showwarning(APP_NAME, "El componente administrativo no responde. Contacte a la Unidad de Sistemas.")

        if not messagebox.askyesno(
            APP_NAME,
            f"Se eliminara la impresora de este equipo:\n\n{p.name}\n({p.kind} - {p.address})\n\n"
            "Utilice esta opcion si la PC cambio de area y esta impresora ya no es necesaria.\n\n"
            "¿Desea continuar y retirar esta impresora de Windows?",
            icon="warning",
        ):
            return

        self.set_busy(True)
        self.set_banner(f"Eliminando impresora '{p.name}'...", BLUE)
        self.pending = {"name": p.name, "op": "Remove"}
        self.active_id = ipc.submit(self.dirs, p.name, "Remove")
        self.sent_at = time.time()
        self.pb["value"] = 2
        self.set_log([f"Solicitando eliminacion de la impresora '{p.name}'..."])
        self.phase.config(text="Solicitud enviada al componente administrativo.")
        self.after(500, self._poll)

    def rename_printer_gui(self) -> None:
        p = self.selected()
        if not p:
            return messagebox.showinfo(APP_NAME, "Seleccione primero la impresora que desea renombrar.")
        if not self.service_ok:
            return messagebox.showwarning(APP_NAME, "El componente administrativo no responde. Contacte a la Unidad de Sistemas.")
        self._show_rename_dialog(p)

    def _show_rename_dialog(self, p: PrinterInfo) -> None:
        dlg = tk.Toplevel(self)
        dlg.title(f"{APP_NAME} - Codificar y Renombrar Impresora")
        dlg.geometry("700x560")
        dlg.minsize(620, 500)
        dlg.transient(self)
        dlg.grab_set()

        head = tk.Frame(dlg, bg=BLUE)
        head.pack(fill="x")
        tk.Label(head, text="CODIFICACION INSTITUCIONAL DE IMPRESORA", fg="white", bg=BLUE,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=14, pady=10)

        body = ttk.Frame(dlg, padding=14)
        body.pack(fill="both", expand=True)

        sug = suggest_naming_for_printer(p)

        row = 0
        def add_row(label, widget):
            nonlocal row
            ttk.Label(body, text=label, font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", pady=5)
            widget.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=5)
            row += 1

        body.columnconfigure(1, weight=1)

        # Nombre actual
        lbl_actual = ttk.Label(body, text=f"{p.name}  ({p.kind} - {p.address})", foreground="#333", font=("Segoe UI", 9, "italic"))
        add_row("Nombre Actual:", lbl_actual)

        # 1. Área
        var_area = tk.StringVar(value=sug["area"])
        ent_area = ttk.Entry(body, textvariable=var_area)
        add_row("Area / Direccion:", ent_area)

        # 2. Unidad
        var_unidad = tk.StringVar(value=sug["unidad"])
        ent_unidad = ttk.Entry(body, textvariable=var_unidad)
        add_row("Unidad / Dpto:", ent_unidad)

        # 3. Número de impresora
        var_num = tk.StringVar(value=sug["numero"])
        ent_num = ttk.Entry(body, textvariable=var_num)
        add_row("Nro Impresora:", ent_num)

        # 4. Modelo (auto-detectado)
        var_modelo = tk.StringVar(value=sug["modelo"])
        ent_modelo = ttk.Entry(body, textvariable=var_modelo)
        add_row("Modelo Detectado:", ent_modelo)

        # 5. Color / BN
        var_color = tk.BooleanVar(value=sug["es_color"])
        chk_color = ttk.Checkbutton(body, text="Equipo a Color (desmarcar para Monocromo B/N)", variable=var_color)
        add_row("Tipo de Color:", chk_color)

        # 6. Estilo
        estilos = [
            ("estandar", "Estandar: [AREA]-[UNIDAD]-IMP[01] ([MODELO] Color/BN)"),
            ("clasico", "Clasico: [AREA] - [UNIDAD] - IMP [01] ([MODELO])"),
            ("corto", "Corto Codificado: [AREA]_[UNIDAD]_IMP[01]"),
        ]
        cb_estilo = ttk.Combobox(body, state="readonly", values=[e[1] for e in estilos])
        cb_estilo.current(0)
        add_row("Estilo de Nombre:", cb_estilo)

        # 7. Vista previa en tiempo real
        var_final = tk.StringVar()
        ttk.Label(body, text="Nombre Resultante:", font=("Segoe UI", 9, "bold"), foreground=BLUE).grid(row=row, column=0, sticky="w", pady=10)
        ent_final = ttk.Entry(body, textvariable=var_final, font=("Segoe UI", 10, "bold"), foreground=BLUE)
        ent_final.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=10)
        row += 1

        ttk.Label(body, text="* Puedes modificar el nombre resultante en el campo superior antes de aplicar.",
                  font=("Segoe UI", 8, "italic"), foreground="#666").grid(row=row, column=0, columnspan=2, sticky="w", pady=(0, 10))
        row += 1

        def update_preview(*_):
            idx = cb_estilo.current()
            est = estilos[idx][0] if idx >= 0 else "estandar"
            gen = build_printer_name(
                area=var_area.get(),
                unidad=var_unidad.get(),
                numero=var_num.get(),
                modelo=var_modelo.get(),
                es_color=var_color.get(),
                estilo=est,
            )
            var_final.set(gen)

        var_area.trace_add("write", update_preview)
        var_unidad.trace_add("write", update_preview)
        var_num.trace_add("write", update_preview)
        var_modelo.trace_add("write", update_preview)
        var_color.trace_add("write", update_preview)
        cb_estilo.bind("<<ComboboxSelected>>", update_preview)
        update_preview()

        def apply_rename():
            nuevo = sanitize_printer_name(var_final.get().strip())
            if not nuevo:
                return messagebox.showwarning("Renombrar", "Debe ingresar un nombre valido.", parent=dlg)
            if nuevo == p.name:
                return messagebox.showinfo("Renombrar", "El nombre es identico al actual.", parent=dlg)
            if not messagebox.askyesno(
                "Confirmar Cambio de Nombre",
                f"Se cambiara el nombre de la impresora en Windows:\n\nActual: {p.name}\nNuevo:  {nuevo}\n\n¿Desea aplicar el cambio?",
                parent=dlg,
            ):
                return
            dlg.destroy()
            self.set_busy(True)
            self.set_banner(f"Cambiando nombre a '{nuevo}'...", BLUE)
            self.pending = {"name": p.name, "new_name": nuevo, "op": "Rename"}
            self.active_id = ipc.submit(self.dirs, p.name, "Rename", new_name=nuevo)
            self.sent_at = time.time()
            self.pb["value"] = 4
            self.set_log([f"Renombrando '{p.name}' -> '{nuevo}'..."])
            self.phase.config(text="Solicitud enviada al componente administrativo.")
            self.after(500, self._poll)

        bot_bar = ttk.Frame(dlg, padding=(14, 0, 14, 14))
        bot_bar.pack(fill="x")
        btn_apply = ttk.Button(bot_bar, text="APLICAR NUEVO NOMBRE", command=apply_rename)
        btn_apply.pack(side="left", padx=(0, 8), ipady=5)
        btn_cancel = ttk.Button(bot_bar, text="CANCELAR", command=dlg.destroy)
        btn_cancel.pack(side="right", ipady=5)

    def generate_r02(self) -> None:
        p = self.selected()
        if not p:
            if self.last_target_printer and self.last_target_printer in self.printers:
                p = self.printers[self.last_target_printer]
            else:
                return messagebox.showinfo(APP_NAME, "Seleccione una impresora de la lista para generar el Formulario R-02.")

        acciones = []
        estado_equipo = f"Operativo (Windows: {p.status})" if p.status == "Normal" else f"Atencion: {p.status}"
        comentario_final = (
            "Servicio de soporte tecnico finalizado exitosamente. "
            "Se verifico la configuracion en el sistema operativo y se entrega al funcionario conforme."
        )

        if self.last_target_printer == p.name and self.last_res:
            res_log = self.last_res.get("log", [])
            for line in res_log:
                if line.startswith("[") and "/" in line[:6]:
                    acciones.append(line.split("] ", 1)[-1])
            if self.last_res.get("state") in ("done", "warning"):
                estado_equipo = "Operativo tras reinstalacion controlada"
                comentario_final = (
                    "Reinstalacion completada exitosamente. Se depuro la cola de impresion, se restablecio el puerto "
                    "y se preservaron el controlador y preferencias. Equipo listo para impresion."
                )
            else:
                estado_equipo = f"No operativo / Falla en fase {self.last_res.get('failed_phase', 0)}"
                comentario_final = f"Reinstalacion no pudo completarse: {self.last_res.get('message', '')}. Requiere intervencion tecnica adicional."
        elif self.last_target_printer == p.name and self.last_diagnose:
            acciones.append("Diagnostico tecnico de red, puerto, spooler y controlador.")
            for line in self.last_diagnose[0]:
                if line.startswith("[OK]") or line.startswith("[AVISO]") or line.startswith("[FALLO]"):
                    acciones.append(line)
            comentario_final = f"Diagnostico concluido. Conclusion tecnica: {self.last_diagnose[1]}"
        else:
            acciones = [
                "Diagnostico de comunicacion y estado general de la impresora.",
                "Verificacion de cola de impresion y servicios de spooler de Windows.",
                "Revision de estado de controlador y parametros duplex."
            ]

        que_se_hizo_texto = "\n".join(f"- {a}" for a in acciones)
        self._show_r02_dialog(p, que_se_hizo_texto, estado_equipo, comentario_final)

    def _show_r02_dialog(self, p: PrinterInfo, que_se_hizo: str, estado_equipo: str, comentario_final: str) -> None:
        dlg = tk.Toplevel(self)
        dlg.title("DocPrinter TI - Formulario R-02 (Reporte de Servicio Tecnico)")
        dlg.geometry("740x660")
        dlg.minsize(640, 560)
        dlg.transient(self)
        dlg.grab_set()

        head = tk.Frame(dlg, bg=BLUE)
        head.pack(fill="x")
        tk.Label(head, text="DATOS PARA FINALIZACION DE SOPORTE (FORMULARIO R-02)", fg="white", bg=BLUE,
                 font=("Segoe UI", 12, "bold")).pack(side="left", padx=14, pady=10)

        body = ttk.Frame(dlg, padding=12)
        body.pack(fill="both", expand=True)

        row = 0
        def add_row(label, widget):
            nonlocal row
            ttk.Label(body, text=label, font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="w", pady=4)
            widget.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
            row += 1

        body.columnconfigure(1, weight=1)

        info_lbl = ttk.Label(body, text=f"{p.name}  |  {p.kind} ({p.address})  |  Driver: {p.driver}", foreground="#333")
        add_row("Impresora:", info_lbl)

        var_tipo = tk.StringVar(value="IMPRESORA")
        ent_tipo = ttk.Entry(body, textvariable=var_tipo)
        add_row("Tipo de Servicio:", ent_tipo)

        var_estado = tk.StringVar(value=estado_equipo)
        ent_estado = ttk.Entry(body, textvariable=var_estado)
        add_row("Estado del Equipo:", ent_estado)

        var_material = tk.StringVar(value="NINGUNO")
        ent_material = ttk.Entry(body, textvariable=var_material)
        add_row("Material Utilizado:", ent_material)

        ttk.Label(body, text="Que se hizo:", font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="nw", pady=4)
        txt_hecho = tk.Text(body, height=7, font=("Consolas", 9), wrap="word")
        txt_hecho.insert("1.0", que_se_hizo)
        txt_hecho.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
        row += 1

        ttk.Label(body, text="Comentario Final:", font=("Segoe UI", 9, "bold")).grid(row=row, column=0, sticky="nw", pady=4)
        txt_coment = tk.Text(body, height=4, font=("Segoe UI", 9), wrap="word")
        txt_coment.insert("1.0", comentario_final)
        txt_coment.grid(row=row, column=1, sticky="ew", padx=(8, 0), pady=4)
        row += 1

        lbl_status = ttk.Label(body, text="", font=("Segoe UI", 9, "bold"))
        lbl_status.grid(row=row, column=0, columnspan=2, sticky="w", pady=6)
        row += 1

        saved_path: list[Path] = []

        from .report_r02 import generate_r02

        def build_current_text() -> str:
            return generate_r02(
                p,
                que_se_hizo=txt_hecho.get("1.0", "end").strip(),
                estado_equipo=var_estado.get().strip(),
                comentario_finalizacion=txt_coment.get("1.0", "end").strip(),
                material_utilizado=var_material.get().strip() or "NINGUNO",
                tipo_servicio=var_tipo.get().strip() or "IMPRESORA",
            )

        def copy_to_clipboard():
            text = build_current_text()
            dlg.clipboard_clear()
            dlg.clipboard_append(text)
            dlg.update()
            lbl_status.config(text="Copiado al portapapeles. Listo para pegar en tu sistema de soporte.", foreground=GREEN)

        def save_report():
            try:
                f, _ = save_r02_report(
                    p,
                    que_se_hizo=txt_hecho.get("1.0", "end").strip(),
                    estado_equipo=var_estado.get().strip(),
                    comentario_finalizacion=txt_coment.get("1.0", "end").strip(),
                    material_utilizado=var_material.get().strip() or "NINGUNO",
                    tipo_servicio=var_tipo.get().strip() or "IMPRESORA",
                )
                saved_path.append(f)
                lbl_status.config(text=f"Reporte guardado con exito en:\n{f}", foreground=GREEN)
                btn_open.state(["!disabled"])
                messagebox.showinfo("Formulario R-02", f"Reporte R-02 guardado en el Escritorio:\n\n{f.name}", parent=dlg)
            except Exception as ex:  # noqa: BLE001
                lbl_status.config(text=f"Error al guardar: {ex}", foreground=RED)
                messagebox.showerror("Error", f"No se pudo guardar el reporte:\n{ex}", parent=dlg)

        def open_report():
            if saved_path and saved_path[-1].exists():
                try:
                    os.startfile(str(saved_path[-1]))
                except Exception as ex:  # noqa: BLE001
                    messagebox.showerror("Error", f"No se pudo abrir el archivo:\n{ex}", parent=dlg)

        bot_bar = ttk.Frame(dlg, padding=(12, 0, 12, 12))
        bot_bar.pack(fill="x")
        btn_copy = ttk.Button(bot_bar, text="COPIAR AL PORTAPAPELES", command=copy_to_clipboard)
        btn_copy.pack(side="left", padx=(0, 8), ipady=4)
        btn_save = ttk.Button(bot_bar, text="GUARDAR EN ESCRITORIO", command=save_report)
        btn_save.pack(side="left", padx=(0, 8), ipady=4)
        btn_open = ttk.Button(bot_bar, text="ABRIR ARCHIVO", command=open_report)
        btn_open.pack(side="left", padx=(0, 8), ipady=4)
        btn_open.state(["disabled"])
        btn_close = ttk.Button(bot_bar, text="CERRAR", command=dlg.destroy)
        btn_close.pack(side="right", ipady=4)


def main(fake: bool = False) -> int:
    from .backends import get_backend
    backend = get_backend(fake)
    stop = threading.Event()
    if fake:   # modo desarrollo: carpeta temporal + helper en un hilo, todo simulado
        dirs = get_dirs(Path(tempfile.mkdtemp(prefix="dpti-fake-"))).ensure()
        from .helper import run_loop
        threading.Thread(target=run_loop, args=(backend, dirs, stop, 0.5, lambda s: time.sleep(0.15)), daemon=True).start()
    else:
        dirs = get_dirs()
    try:
        app = App(backend, dirs, "UNIDAD DE SISTEMAS - SOPORTE TECNICO", fake)
        app.mainloop()
    except Exception as e:  # noqa: BLE001
        crash = Path(tempfile.gettempdir()) / "DocPrinterTI-error.log"
        crash.write_text(repr(e), encoding="utf-8")
        raise
    finally:
        stop.set()
    return 0
