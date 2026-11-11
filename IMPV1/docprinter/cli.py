"""Linea de comandos para desarrollo y soporte:  python -m docprinter cli list | diagnose NOMBRE | reinstall NOMBRE [--simulate]"""
from __future__ import annotations

import sys

from . import oplog, workflow
from .backends import get_backend
from .paths import get_dirs


def main(argv: list[str], fake: bool = False) -> int:
    b = get_backend(fake)
    cmd = argv[0] if argv else "list"
    if cmd == "list":
        for p in b.list_printers():
            print(f"{p.name:32} {p.kind:11} {p.address:22} {p.driver:36} {p.status}")
        return 0
    if len(argv) < 2:
        print("Falta el nombre de la impresora.")
        return 2
    name = argv[1]
    if cmd == "diagnose":
        lines, conclusion = workflow.diagnose(b, name)
        print("\n".join(lines))
        print("\nCONCLUSION:", conclusion)
        return 0
    if cmd == "reinstall":
        dirs = get_dirs().ensure()
        res = workflow.reinstall(b, name, simulate="--simulate" in argv, on_update=lambda r: None,
                                 oplog=lambda **kw: oplog.write(dirs.logs, **kw), backup_dir=dirs.backups)
        print("\n".join(res.log))
        print("\n" + res.message)
        if res.user_action:
            print(res.user_action)
        return 0 if res.state in ("done", "warning") else 1
    if cmd == "report":
        p = b.get_printer(name)
        from .report_r02 import save_r02_report
        f, content = save_r02_report(p)
        print(content)
        print(f"Reporte guardado en: {f}")
        return 0
    if cmd == "remove":
        b.remove_printer(name)
        print(f"Impresora '{name}' eliminada correctamente.")
        return 0
    if cmd == "rename":
        if len(argv) < 3:
            print("Uso: rename NOMBRE NUEVO_NOMBRE")
            return 2
        new_name = argv[2]
        b.rename_printer(name, new_name)
        print(f"Impresora '{name}' renombrada a '{new_name}'.")
        return 0
    print("Comandos: list | diagnose NOMBRE | reinstall NOMBRE [--simulate] | report NOMBRE | rename NOMBRE NUEVO | remove NOMBRE")
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
