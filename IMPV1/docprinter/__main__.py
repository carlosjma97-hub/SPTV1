"""Punto de entrada unico:  gui (por defecto) | helper | cli | setup   (+ --fake para usar impresoras simuladas)"""
from __future__ import annotations

import sys


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fake = "--fake" in argv
    argv = [a for a in argv if a != "--fake"]
    cmd = argv[0] if argv else "gui"
    rest = argv[1:]
    if cmd == "gui":
        from .gui import main as run
        return run(fake)
    if cmd == "helper":
        from .helper import main as run
        return run(rest, fake)
    if cmd == "cli":
        from .cli import main as run
        return run(rest, fake)
    if cmd == "setup":
        from .admin_setup import main as run
        return run(rest)
    if sys.stdout:
        print("Uso: python -m docprinter [gui|helper|cli|setup] [--fake]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
