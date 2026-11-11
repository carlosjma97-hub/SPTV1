import queue
import threading
import time
from datetime import datetime
from copier_engine import copy_with_robocopy


class QueueManager:
    def __init__(self, database):
        self.database = database
        self.events = queue.Queue()
        self.tasks = []
        self.lock = threading.Lock()
        self.cancel_event = threading.Event()
        self.thread = None

    @property
    def running(self):
        return self.thread is not None and self.thread.is_alive()

    def add(self, task):
        row_id = self.database.add_task(task)
        item = {**task, 'id': row_id, 'estado': 'EN ESPERA'}
        with self.lock:
            self.tasks.append(item)
        self.events.put({'type': 'task_added', 'task': item})

    def start(self):
        if self.running:
            return
        self.cancel_event.clear()
        self.thread = threading.Thread(target=self._run, daemon=True,
                                       name='PasarelaBK-Worker')
        self.thread.start()

    def cancel(self):
        self.cancel_event.set()
        self.events.put({'type': 'message', 'text': 'Cancelación solicitada.'})

    def _run(self):
        with self.lock:
            tasks = list(self.tasks)
        total = len(tasks)
        for index, task in enumerate(tasks):
            if self.cancel_event.is_set():
                break
            started = time.monotonic()
            self.database.update_task(task['id'], estado='EN PROGRESO',
                                      fecha_inicio=datetime.now().isoformat(timespec='seconds'))
            self.events.put({'type': 'task_status', 'id': task['id'],
                             'status': 'EN PROGRESO'})
            try:
                result = copy_with_robocopy(
                    task['ruta_origen'], task['ruta_destino'],
                    lambda line, tid=task['id']: self.events.put(
                        {'type': 'log', 'id': tid, 'line': line}),
                    self.cancel_event.is_set)
                self.database.update_task(task['id'], **result,
                    fecha_fin=datetime.now().isoformat(timespec='seconds'),
                    duracion_segundos=int(time.monotonic()-started))
                self.events.put({'type': 'task_status', 'id': task['id'],
                                 'status': result['estado']})
            except Exception as exc:
                self.database.update_task(task['id'], estado='FALLIDO',
                    fecha_fin=datetime.now().isoformat(timespec='seconds'),
                    duracion_segundos=int(time.monotonic()-started), log_resumen=str(exc))
                self.events.put({'type': 'task_status', 'id': task['id'],
                                 'status': 'FALLIDO'})
                self.events.put({'type': 'error', 'id': task['id'], 'text': str(exc)})
                if isinstance(exc, InterruptedError):
                    break
            self.events.put({'type': 'queue_progress', 'completed': index+1,
                             'total': total})
        self.events.put({'type': 'queue_finished'})
