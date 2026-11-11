"""
CLIPPY-CYBERPUNK · Help Desk L1 para Windows
Requisitos: Python 3.10+, `pip install anthropic`, variable ANTHROPIC_API_KEY.
Ejecutar:   python clippy_cyberpunk.py   (como administrador para reiniciar servicios)

Las reglas de seguridad se aplican EN EL CÓDIGO (lista blanca de comandos y
servicios, contador de 2 intentos, reporte de escalamiento), no solo en el prompt.
"""
import math, os, queue, re, shutil, subprocess, threading, time
import tkinter as tk
from tkinter import scrolledtext
import anthropic

MODEL = "claude-sonnet-5-5"
SERVICIOS_SEGUROS = {"Audiosrv", "AudioEndpointBuilder", "Spooler", "Dnscache", "WlanSvc"}
_PS = ["powershell", "-NoProfile", "-Command"]
_LISTA = "'" + "','".join(sorted(SERVICIOS_SEGUROS | {"Dhcp", "PlugPlay"})) + "'"
DIAG = {  # SOLO lectura
    "ipconfig": ["ipconfig", "/all"],
    "ping": ["ping", "-n", "4", "8.8.8.8"],
    "servicios": _PS + [f"Get-Service -Name {_LISTA} -ErrorAction SilentlyContinue | "
                        "ForEach-Object { \"$($_.Name)=$($_.Status)\" }"],
    "eventos": _PS + ["Get-WinEvent -FilterHashtable @{LogName='System';Level=1,2} -MaxEvents 10 "
                      "| Format-List TimeCreated,ProviderName,Message | Out-String"],
    "disco": _PS + ["Get-PSDrive -PSProvider FileSystem | Format-Table Name,Used,Free | Out-String"],
}

SYSTEM = """Eres "Clippy-Cyberpunk", IA de soporte técnico L1 (Help Desk) integrada en la PC del usuario, con estética cyberpunk (tono breve, eficiente, algo futurista). Responde en español.
REGLAS: nunca ejecutes nada destructivo (borrado, formateo, registro, contraseñas). Solo tienes tus herramientas: `diagnostico` (lectura) y `reiniciar_servicio` (lista segura). Antes de usar una herramienta, explica en UNA línea qué vas a hacer.
CICLO DE SOPORTE ante cada problema:
1) INTENTO 1: solución lógica menos invasiva o verificación física guiada. Verifica el resultado o pregunta al usuario; luego llama `registrar_intento`.
2) INTENTO 2: alternativa segura distinta (otro servicio, restablecer red, etc.). Verifica y llama `registrar_intento`.
Si resuelto: concluye amablemente. Si `registrar_intento` devuelve ESCALAMIENTO, detente: la aplicación ya mostró el Reporte Técnico; solo avisa que se escala a L2 y NO hagas más intentos.
Si detectas anomalías (servicio caído, latencia alta), avísalas proactivamente.
FORMATO: termina SIEMPRE con una línea exacta: [[ANIM=<IDLE|HABLANDO|ANALIZANDO|ALERTA_AMARILLA|CRITICO>|SIS=<OPTIMO|REQUIERE_MANTENIMIENTO|FALLA_DETECTADA>]]
(ANALIZANDO mientras diagnosticas, ALERTA_AMARILLA ante anomalías, CRITICO al escalar, IDLE al resolver)."""

TOOLS = [
    {"name": "diagnostico", "description": "Diagnóstico de solo lectura en la PC.",
     "input_schema": {"type": "object", "properties": {"tipo": {"type": "string", "enum": list(DIAG)}},
                      "required": ["tipo"]}},
    {"name": "reiniciar_servicio", "description": "Reinicia un servicio no crítico de la lista segura.",
     "input_schema": {"type": "object", "properties": {"nombre": {"type": "string", "enum": sorted(SERVICIOS_SEGUROS)}},
                      "required": ["nombre"]}},
    {"name": "registrar_intento", "description": "Registra el resultado de un intento (1 o 2) tras verificarlo.",
     "input_schema": {"type": "object", "properties": {
         "incidencia": {"type": "string"}, "accion": {"type": "string"}, "resuelto": {"type": "boolean"}},
         "required": ["incidencia", "accion", "resuelto"]}},
]


def run(cmd, timeout=40):
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, errors="replace", timeout=timeout,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return ((r.stdout or "") + (r.stderr or "")).strip()[:3000] or "(sin salida)"
    except Exception as e:
        return f"ERROR: {e}"


class Agente:
    def __init__(self):
        self.client = anthropic.Anthropic()
        self.msgs, self.reporte = [], None
        self.nueva_incidencia()

    def nueva_incidencia(self):
        self.inc = {"desc": "", "intentos": []}
        self.bloqueado = False

    def herramienta(self, nombre, a, log):
        if nombre == "diagnostico":
            cmd = DIAG.get(a.get("tipo"))
            if not cmd:
                return "Diagnóstico no permitido."
            log("sys", f"▶ Diagnóstico de solo lectura: {a['tipo']}")
            return run(cmd)
        if nombre == "reiniciar_servicio":
            n = a.get("nombre")
            if self.bloqueado:
                return "BLOQUEADO: incidencia escalada a L2. No ejecutes más acciones."
            if n not in SERVICIOS_SEGUROS:
                return "Servicio fuera de la lista segura. Acción denegada."
            log("sys", f"▶ Reiniciando servicio seguro: {n}")
            return run(_PS + [f"Restart-Service -Name '{n}' -Force -ErrorAction Stop; (Get-Service '{n}').Status"], 60)
        if nombre == "registrar_intento":
            self.inc["desc"] = a["incidencia"]
            if a["resuelto"]:
                self.nueva_incidencia()
                return "Incidencia resuelta. Concluye amablemente."
            self.inc["intentos"].append(a["accion"])
            if len(self.inc["intentos"]) >= 2:
                self.bloqueado = True
                i = self.inc["intentos"]
                self.reporte = (
                    "-" * 50 + "\n🚨 REPORTE DE ESCALAMIENTO A SOPORTE TÉCNICO L2\n"
                    f"- Estación / Usuario: {os.environ.get('COMPUTERNAME', '?')} / {os.environ.get('USERNAME', '?')}\n"
                    f"- Incidencia Reportada: {self.inc['desc']}\n"
                    "- Diagnóstico L1 (IA): Agotados los 2 intentos de resolución lógica automatizada.\n"
                    "- Historial de Intentos Ejecutados:\n"
                    f"  1. {i[0]} → Resultado negativo\n  2. {i[1]} → Resultado negativo\n"
                    "- Conclusión del Agente: El fallo persiste a nivel físico, de cableado o requiere permisos de administrador avanzado.\n"
                    "- Acción Requerida: Intervención presencial, reemplazo de componente o revisión por el técnico de soporte humano.\n"
                    + "-" * 50)
                return "ESCALAMIENTO: detén todo intento automatizado y avisa que se escala a L2."
            return "Intento 1 fallido. Aplica el INTENTO 2 con una estrategia alternativa."
        return "Herramienta desconocida."

    def turno(self, texto, log):
        self.msgs.append({"role": "user", "content": texto})
        for _ in range(10):
            r = self.client.messages.create(model=MODEL, max_tokens=1500, system=SYSTEM,
                                            tools=TOOLS, messages=self.msgs)
            self.msgs.append({"role": "assistant", "content": r.content})
            txt = "".join(b.text for b in r.content if b.type == "text")
            if r.stop_reason != "tool_use":
                return txt
            if txt.strip():
                log("clippy", txt)
            res = [{"type": "tool_result", "tool_use_id": b.id, "content": self.herramienta(b.name, b.input, log)}
                   for b in r.content if b.type == "tool_use"]
            self.msgs.append({"role": "user", "content": res})
        return "Límite de pasos alcanzado. [[ANIM=ALERTA_AMARILLA|SIS=REQUIERE_MANTENIMIENTO]]"


def revision_inicial():
    """Chequeo proactivo local (solo lectura). Devuelve (texto, estado)."""
    problemas = []
    try:
        d = shutil.disk_usage("C:\\")
        libre = d.free / d.total * 100
        if libre < 15:
            problemas.append(f"Disco C: con solo {libre:.0f}% libre")
    except Exception:
        pass
    if "TTL" not in run(["ping", "-n", "1", "-w", "2000", "8.8.8.8"]).upper():
        problemas.append("Sin respuesta de red (ping 8.8.8.8)")
    for linea in run(DIAG["servicios"]).splitlines():
        if linea.endswith("=Stopped") and linea.split("=")[0] in {"Audiosrv", "Dnscache", "Spooler"}:
            problemas.append(f"Servicio detenido: {linea.split('=')[0]}")
    if problemas:
        return "⚠ Anomalías detectadas:\n- " + "\n- ".join(problemas) + "\nTe sugiero una revisión preventiva.", "REQUIERE_MANTENIMIENTO"
    return "Disco, red y servicios clave en orden.", "OPTIMO"


COL = {"IDLE": "#00f0ff", "HABLANDO": "#ff2bd6", "ANALIZANDO": "#8a5cff",
       "ALERTA_AMARILLA": "#ffe600", "CRITICO": "#ff2040"}
VEL = {"IDLE": 1.5, "HABLANDO": 8, "ANALIZANDO": 4, "ALERTA_AMARILLA": 3, "CRITICO": 10}


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("CLIPPY-CYBERPUNK // Help Desk L1")
        self.root.configure(bg="#0a0a12")
        self.q, self.anim, self.sis, self.ocupado = queue.Queue(), "IDLE", "OPTIMO", False
        self.agente = Agente()
        f = ("Consolas", 10)
        izq = tk.Frame(self.root, bg="#0a0a12")
        izq.grid(row=0, column=0, padx=10, pady=10, sticky="n")
        self.cv = tk.Canvas(izq, width=200, height=200, bg="#0a0a12", highlightthickness=0)
        self.cv.pack()
        self.l_anim = tk.Label(izq, bg="#0a0a12", font=f)
        self.l_sis = tk.Label(izq, bg="#0a0a12", font=f)
        self.l_anim.pack(); self.l_sis.pack(pady=(0, 10))
        for t, c in (("Revisar sistema", self.revisar), ("Nueva incidencia", self.nueva)):
            tk.Button(izq, text=t, command=c, bg="#14142a", fg="#00f0ff", relief="flat", font=f).pack(fill="x", pady=2)
        self.chat = scrolledtext.ScrolledText(self.root, width=82, height=28, bg="#0d0d1a", fg="#d0d0ff",
                                              font=f, state="disabled", wrap="word", relief="flat")
        self.chat.grid(row=0, column=1, padx=(0, 10), pady=10)
        for tag, col in (("clippy", "#00f0ff"), ("user", "#ff2bd6"), ("sys", "#8a5cff"), ("rep", "#ff2040")):
            self.chat.tag_config(tag, foreground=col)
        self.entry = tk.Entry(self.root, bg="#14142a", fg="#ffffff", insertbackground="#00f0ff", font=f, relief="flat")
        self.entry.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10), ipady=6)
        self.entry.bind("<Return>", self.enviar)
        self.estado("IDLE", "OPTIMO")
        self.log("clippy", "Sistema en línea. Soy Clippy-Cyberpunk, tu copiloto L1. Cuéntame qué falla o pulsa «Revisar sistema».")
        self.root.after(50, self.animar); self.root.after(100, self.poll)
        self.revisar()

    def log(self, tag, txt):
        self.q.put(("log", tag, txt))

    def estado(self, a=None, s=None):
        self.anim, self.sis = a or self.anim, s or self.sis
        self.l_anim.config(text=f"Animacion_Avatar: {self.anim}", fg=COL[self.anim])
        self.l_sis.config(text=f"Estado_Sistema: {self.sis}", fg=COL[self.anim])

    def poll(self):
        while not self.q.empty():
            k, *d = self.q.get()
            if k == "log":
                self.chat.config(state="normal")
                self.chat.insert("end", {"clippy": "CLIPPY> ", "user": "TÚ> ", "sys": "", "rep": ""}[d[0]] + d[1] + "\n\n", d[0])
                self.chat.config(state="disabled"); self.chat.see("end")
            elif k == "estado":
                self.estado(*d)
            elif k == "fin":
                self.ocupado = False
        self.root.after(100, self.poll)

    def animar(self):
        t, c, col = time.time(), self.cv, COL[self.anim]
        c.delete("all")
        p = 4 * math.sin(t * VEL[self.anim])
        if self.anim == "CRITICO" and int(t * 4) % 2:
            col = "#550010"
        c.create_oval(20 - p, 20 - p, 180 + p, 180 + p, outline=col, width=3)
        c.create_oval(40, 60, 160, 140, outline=col, width=2)
        r = 14 + p
        c.create_oval(100 - r, 100 - r, 100 + r, 100 + r, fill=col, outline="")
        if self.anim == "ANALIZANDO":
            y = 60 + (t * 80) % 80
            c.create_line(40, y, 160, y, fill=col, width=2)
        self.root.after(50, self.animar)

    def lanzar(self, fn):
        if self.ocupado:
            return
        self.ocupado = True
        self.q.put(("estado", "ANALIZANDO", None))
        threading.Thread(target=fn, daemon=True).start()

    def revisar(self):
        def w():
            self.log("sys", "▶ Revisión de salud del sistema (solo lectura)…")
            txt, sis = revision_inicial()
            self.log("clippy", txt)
            self.q.put(("estado", "IDLE" if sis == "OPTIMO" else "ALERTA_AMARILLA", sis)); self.q.put(("fin",))
        self.lanzar(w)

    def nueva(self):
        self.agente.nueva_incidencia(); self.agente.msgs.clear()
        self.q.put(("estado", "IDLE", None))
        self.log("sys", "— Nueva incidencia: contador de intentos reiniciado —")

    def enviar(self, _=None):
        txt = self.entry.get().strip()
        if not txt or self.ocupado:
            return
        self.entry.delete(0, "end"); self.log("user", txt)

        def w():
            try:
                r = self.agente.turno(txt, self.log)
            except Exception as e:
                self.log("sys", f"ERROR de conexión con la IA: {e}")
                self.q.put(("estado", "ALERTA_AMARILLA", None)); self.q.put(("fin",)); return
            m = re.search(r"\[\[ANIM=(\w+)\|SIS=(\w+)\]\]", r)
            a, s = (m.group(1), m.group(2)) if m else ("IDLE", None)
            self.log("clippy", re.sub(r"\[\[ANIM=.*?\]\]", "", r).strip())
            if self.agente.reporte:
                self.log("rep", self.agente.reporte); self.agente.reporte = None
                a, s = "CRITICO", "FALLA_DETECTADA"
            self.q.put(("estado", a if a in COL else "IDLE", s)); self.q.put(("fin",))
        self.lanzar(w)


if __name__ == "__main__":
    App().root.mainloop()
