import os
import re
import subprocess
from pathlib import Path


def windows_long_path(path):
    path = os.path.abspath(path)
    if path.startswith('\\\\?\\'):
        return path
    if path.startswith('\\\\'):
        return '\\\\?\\UNC\\' + path.lstrip('\\')
    return '\\\\?\\' + path


def copy_with_robocopy(source, destination, on_progress, should_cancel):
    if os.name != 'nt':
        raise RuntimeError('Robocopy solo está disponible en Windows.')
    if not os.path.isdir(source):
        raise FileNotFoundError(f'No existe el origen: {source}')
    Path(destination).mkdir(parents=True, exist_ok=True)
    log_path = os.path.join(os.environ.get('TEMP', '.'), 'pasarel bak_robocopy.log')
    cmd = ['robocopy', windows_long_path(source), windows_long_path(destination),
           '/E','/COPY:DAT','/DCOPY:DAT','/R:1','/W:2','/XJ','/NP','/TEE',
           '/LOG+:' + log_path]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding='oem', errors='replace',
                            creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    lines = []
    try:
        for line in proc.stdout:
            line = line.rstrip()
            lines.append(line)
            on_progress(line)
            if should_cancel():
                proc.terminate()
                proc.wait(timeout=10)
                raise InterruptedError('Cancelado por el usuario')
        code = proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()
    log = '\n'.join(lines[-100:])
    if code >= 8:
        raise RuntimeError(f'Robocopy terminó con código {code}.\n' + '\n'.join(lines[-20:]))
    files = re.search(r'^\s*Files\s*:\s*([\d,]+)\s+([\d,]+)', log, re.M)
    failed = re.search(r'^\s*Failed\s*:\s*([\d,]+)', log, re.M)
    copied = int(files.group(2).replace(',', '')) if files else 0
    failures = int(failed.group(1).replace(',', '')) if failed else 0
    total = 0
    for root, _, names in os.walk(destination, onerror=lambda _: None):
        for name in names:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return {'total_bytes': total, 'total_gb': total/(1024**3),
            'total_archivos': copied, 'archivos_fallidos': failures,
            'log_resumen': log,
            'estado': 'EXITOSO' if failures == 0 else 'CON ADVERTENCIAS'}
