PasarelaBK - Consolidador de Backups
====================================

Requisitos: Windows 10/11, Python 3.10+ y Robocopy (incluido en Windows).

Prueba desde el código:
  py -m venv .venv
  .venv\Scripts\Activate.ps1
  py -m pip install -r requirements.txt
  py main.py

La aplicación permite agregar carpetas a una cola secuencial, iniciar la copia,
consultar SQLite y exportar el historial a Excel. La base se crea como
pasarela_backups.db en el directorio desde el que se ejecuta la app.

Compilar exe sin consola:
  py -m PyInstaller --noconfirm --clean --onefile --windowed --name PasarelaBK main.py
  El resultado se genera en dist\PasarelaBK.exe.

Nota: 'Pausar / Cancelar' actualmente cancela. El progreso visible de cola es
por tareas; Robocopy escribe detalles de salida al panel de registro. Prueba
primero con carpetas de prueba y valida los permisos de los discos involucrados.
