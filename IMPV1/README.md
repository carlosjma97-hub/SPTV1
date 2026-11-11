# DocPrinter TI (Python)

Reinstalacion controlada de impresoras en Windows 10/11 para funcionarios, sin privilegios de administrador.

## Programas separados (carpeta `docprinter/`)
| Archivo | Que es | Corre como |
|---|---|---|
| `workflow.py` | Logica: diagnostico y reinstalacion en 8 fases + rollback. **No sabe nada de Windows** | (libreria) |
| `backend_windows.py` | Backend real: cmdlets de PowerShell con scripts fijos y parametros como JSON | segun quien llame |
| `backend_fake.py` | Impresoras simuladas en memoria (para desarrollar/probar sin Windows) | cualquiera |
| `helper.py` + `ipc.py` | Componente administrativo: lee la cola, valida y ejecuta solo `Reinstall`/`Simulate` | SYSTEM (tarea programada) |
| `gui.py` | Interfaz Tkinter | usuario normal |
| `admin_setup.py` | Instala/desinstala: carpetas, permisos (`icacls`) y tarea (`schtasks`) | administrador |
| `cli.py` | Linea de comandos para soporte y depuracion | segun quien llame |
| `naming.py` | Codificacion y reglas de nomenclatura institucional | usuario / soporte |
| `report_r02.py` | Generador de Reporte de Servicio Tecnico (Formulario R-02) | usuario / soporte |
| `oplog.py` | Registro CSV/TXT de operaciones | helper |

Flujo: GUI -> archivo JSON en `ProgramData\DocPrinterTI\queue` -> helper valida y ejecuta -> escribe `results\<id>.json` -> GUI muestra el progreso.

## Empezar en VS Code (cualquier sistema)
```
pip install -r requirements-dev.txt
python -m pytest -v                       # 47 pruebas (la de GUI solo si hay pantalla)
python -m docprinter gui --fake           # interfaz completa con impresoras simuladas
python -m docprinter cli list --fake
python -m docprinter cli reinstall "HP LaserJet Contabilidad" --fake
python -m docprinter cli report "HP LaserJet Contabilidad" --fake
python -m docprinter cli rename "HP LaserJet Contabilidad" "FINANZAS-CONT-IMP01" --fake
python -m docprinter cli remove "HP LaserJet Contabilidad" --fake
```
En VS Code: abrir la carpeta, F5 y elegir una configuracion de `.vscode/launch.json`.

## Probar con impresoras REALES (en Windows)
1. `python -m docprinter cli list`  -> lee sus impresoras reales (usuario normal).
2. `python -m docprinter cli diagnose "NOMBRE EXACTO"` -> solo lectura.
3. Terminal **como administrador**: `python -m docprinter cli reinstall "NOMBRE" --simulate` y luego sin `--simulate`.
4. Si algo falla, el error de PowerShell sale tal cual; el codigo esta en `backend_windows.py` (scripts `_LIST`, `_ADD_PORT`, `_ADD_PRINTER`...).

## Compilar e instalar (en TU PC con Windows)
`build\build.bat`  -> ejecuta pruebas, genera `dist\DocPrinterTI\DocPrinterTI.exe` y, si tiene NSIS, `build\DocPrinterTI_Setup.exe`
(instala en Program Files, crea `Uninstall.exe`, registra el programa en Windows y la tarea SYSTEM).
Sin instalador: como administrador `python -m docprinter setup install` / `setup uninstall` / `setup status`.
Registro de errores de instalacion: `C:\ProgramData\DocPrinterTI-instalacion.log`.

## Que esta probado y que no
Probado automaticamente: logica de las 8 fases, rollback, validacion de solicitudes, que no toque otras impresoras,
comandos de instalacion, interfaz con impresoras simuladas.
**NO probado (requiere Windows real):** los cmdlets en `backend_windows.py` y `schtasks`/`icacls` reales.
