import sqlite3
from pathlib import Path


class BackupDatabase:
    FIELDS = ('codigo_ticket', 'usuario_desvinculado', 'area_gerencia',
              'tecnico_responsable', 'ruta_origen', 'ruta_destino')

    def __init__(self, path):
        self.path = str(path)
        self.initialize()

    def connect(self):
        conn = sqlite3.connect(self.path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def initialize(self):
        with self.connect() as conn:
            conn.execute('''CREATE TABLE IF NOT EXISTS registro_backups (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                codigo_ticket TEXT NOT NULL, usuario_desvinculado TEXT NOT NULL,
                area_gerencia TEXT NOT NULL, tecnico_responsable TEXT NOT NULL,
                ruta_origen TEXT NOT NULL, ruta_destino TEXT NOT NULL,
                total_bytes REAL DEFAULT 0, total_gb REAL DEFAULT 0,
                total_archivos INTEGER DEFAULT 0, archivos_fallidos INTEGER DEFAULT 0,
                fecha_inicio TEXT, fecha_fin TEXT, duracion_segundos INTEGER DEFAULT 0,
                estado TEXT NOT NULL DEFAULT 'EN ESPERA', log_resumen TEXT DEFAULT '')''')

    def add_task(self, task):
        with self.connect() as conn:
            cur = conn.execute(
                f"INSERT INTO registro_backups ({','.join(self.FIELDS)},estado) "
                f"VALUES ({','.join('?' for _ in self.FIELDS)},'EN ESPERA')",
                tuple(task[k] for k in self.FIELDS))
            return cur.lastrowid

    def update_task(self, row_id, **values):
        allowed = {'total_bytes','total_gb','total_archivos','archivos_fallidos',
                   'fecha_inicio','fecha_fin','duracion_segundos','estado','log_resumen'}
        if set(values) - allowed:
            raise ValueError('Campo de actualización no permitido')
        if values:
            sql = ','.join(f'{k}=?' for k in values)
            with self.connect() as conn:
                conn.execute(f'UPDATE registro_backups SET {sql} WHERE id=?',
                             (*values.values(), row_id))

    def search(self, query=''):
        q = query.strip()
        like = f'%{q}%'
        with self.connect() as conn:
            rows = conn.execute('''SELECT * FROM registro_backups
                WHERE ?='' OR codigo_ticket LIKE ? OR usuario_desvinculado LIKE ?
                OR area_gerencia LIKE ? OR fecha_inicio LIKE ? ORDER BY id DESC''',
                (q, like, like, like, like)).fetchall()
        return [dict(r) for r in rows]
