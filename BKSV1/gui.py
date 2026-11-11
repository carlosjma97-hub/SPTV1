import uuid
from datetime import datetime
from tkinter import filedialog, messagebox, ttk
import customtkinter as ctk
from openpyxl import Workbook
from queue_manager import QueueManager


class PasarelaApp(ctk.CTk):
    def __init__(self, database):
        super().__init__()
        self.database = database
        self.manager = QueueManager(database)
        self.title('PasarelaBK - Consolidador de Backups')
        self.geometry('1180x780')
        ctk.set_appearance_mode('System')
        ctk.set_default_color_theme('blue')
        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill='both', expand=True, padx=12, pady=12)
        self.queue_tab = self.tabs.add('Cola de trabajos')
        self.history_tab = self.tabs.add('Historial y buscador')
        self._build_queue()
        self._build_history()
        self.refresh_history()
        self.after(150, self._poll_events)

    def _build_queue(self):
        form = ctk.CTkFrame(self.queue_tab)
        form.pack(fill='x', padx=8, pady=8)
        form.grid_columnconfigure(1, weight=1)
        specs = [('N° Ticket / Código','ticket'),('Usuario desvinculado','user'),
                 ('Gerencia / Área','area'),('Técnico TI responsable','tech'),
                 ('Ruta origen','source'),('Ruta destino','destination')]
        self.fields = {}
        for row, (label, key) in enumerate(specs):
            ctk.CTkLabel(form, text=label).grid(row=row,column=0,padx=8,pady=5,sticky='w')
            entry = ctk.CTkEntry(form)
            entry.grid(row=row,column=1,padx=8,pady=5,sticky='ew')
            self.fields[key] = entry
            if key == 'ticket':
                entry.insert(0, self._new_ticket())
            if key in ('source','destination'):
                ctk.CTkButton(form,text='Examinar',width=100,
                    command=lambda k=key:self._browse(k)).grid(row=row,column=2,padx=8,pady=5)
        ctk.CTkButton(form,text='+ AGREGAR A LA COLA DE COPIA',
                      command=self.add_task).grid(row=6,column=0,columnspan=3,padx=8,pady=10)
        self.task_tree = self._tree(self.queue_tab,
            ('ticket','user','source','destination','status'),
            ('Ticket','Usuario','Origen','Destino','Estado'),12)
        controls = ctk.CTkFrame(self.queue_tab)
        controls.pack(fill='x',padx=8,pady=8)
        ctk.CTkButton(controls,text='▶ INICIAR PROCESAMIENTO DE COLA (MODO NOCTURNO)',
                      command=self.start_queue).pack(side='left',padx=8,pady=8)
        ctk.CTkButton(controls,text='Pausar / Cancelar Cola',
                      command=self.manager.cancel).pack(side='left',padx=8,pady=8)
        self.progress = ctk.CTkProgressBar(controls)
        self.progress.pack(side='left',fill='x',expand=True,padx=12)
        self.progress.set(0)
        self.progress_label = ctk.CTkLabel(controls,text='Cola: 0/0')
        self.progress_label.pack(side='right',padx=8)
        self.log_box = ctk.CTkTextbox(self.queue_tab,height=100)
        self.log_box.pack(fill='x',padx=8,pady=8)

    def _build_history(self):
        bar = ctk.CTkFrame(self.history_tab)
        bar.pack(fill='x',padx=8,pady=8)
        self.search_entry = ctk.CTkEntry(bar,placeholder_text='Buscar ticket, usuario, área o fecha')
        self.search_entry.pack(side='left',fill='x',expand=True,padx=8,pady=8)
        self.search_entry.bind('<Return>',lambda _:self.refresh_history())
        ctk.CTkButton(bar,text='Buscar',command=self.refresh_history).pack(side='left',padx=8)
        ctk.CTkButton(bar,text='Exportar historial a Excel (.xlsx)',
                      command=self.export_excel).pack(side='right',padx=8)
        cols=('ticket','user','area','source','destination','start','status','files','failed')
        heads=('Ticket','Usuario','Gerencia','Origen','Destino','Fecha inicio','Estado','Archivos','Fallidos')
        self.history_tree = self._tree(self.history_tab,cols,heads,24)

    def _tree(self,parent,columns,headings,height):
        frame=ctk.CTkFrame(parent); frame.pack(fill='both',expand=True,padx=8,pady=8)
        tree=ttk.Treeview(frame,columns=columns,show='headings',height=height)
        widths=[120,150,180,220,220,150,140,80,80]
        for i,(col,head) in enumerate(zip(columns,headings)):
            tree.heading(col,text=head); tree.column(col,width=widths[min(i,len(widths)-1)],anchor='w')
        ys=ttk.Scrollbar(frame,orient='vertical',command=tree.yview)
        xs=ttk.Scrollbar(frame,orient='horizontal',command=tree.xview)
        tree.configure(yscrollcommand=ys.set,xscrollcommand=xs.set)
        tree.grid(row=0,column=0,sticky='nsew'); ys.grid(row=0,column=1,sticky='ns')
        xs.grid(row=1,column=0,sticky='ew'); frame.grid_rowconfigure(0,weight=1)
        frame.grid_columnconfigure(0,weight=1)
        return tree

    def _new_ticket(self):
        return f'BK-{datetime.now():%Y}-{uuid.uuid4().hex[:4].upper()}'

    def _browse(self,key):
        path=filedialog.askdirectory()
        if path:
            self.fields[key].delete(0,'end'); self.fields[key].insert(0,path)

    def add_task(self):
        vals={key:self.fields[key].get().strip() for key in self.fields}
        if any(not value for value in vals.values()):
            messagebox.showerror('Datos incompletos','Completa todos los campos.'); return
        task={'codigo_ticket':vals['ticket'],'usuario_desvinculado':vals['user'],
              'area_gerencia':vals['area'],'tecnico_responsable':vals['tech'],
              'ruta_origen':vals['source'],'ruta_destino':vals['destination']}
        try: self.manager.add(task)
        except Exception as exc: messagebox.showerror('Error',str(exc)); return
        for key,entry in self.fields.items():
            entry.delete(0,'end')
            if key=='ticket': entry.insert(0,self._new_ticket())

    def start_queue(self):
        if self.manager.running: return
        self.manager.start(); self._log('Procesamiento secuencial iniciado.')

    def _poll_events(self):
        while True:
            try: event=self.manager.events.get_nowait()
            except Exception: break
            kind=event['type']
            if kind=='task_added':
                t=event['task']; self.task_tree.insert('', 'end',iid=str(t['id']),
                    values=(t['codigo_ticket'],t['usuario_desvinculado'],t['ruta_origen'],t['ruta_destino'],t['estado']))
            elif kind=='task_status':
                iid=str(event['id'])
                if self.task_tree.exists(iid):
                    values=list(self.task_tree.item(iid,'values')); values[-1]=event['status']
                    self.task_tree.item(iid,values=values)
                self._log(f"Tarea {iid}: {event['status']}"); self.refresh_history()
            elif kind=='log': self._log(event['line'])
            elif kind=='error': self._log(f"ERROR tarea {event['id']}: {event['text']}")
            elif kind=='message': self._log(event['text'])
            elif kind=='queue_progress':
                total=max(1,event['total']); self.progress.set(event['completed']/total)
                self.progress_label.configure(text=f"Cola: {event['completed']}/{event['total']}")
            elif kind=='queue_finished':
                self._log('Procesamiento de cola finalizado.'); self.refresh_history()
        self.after(150,self._poll_events)

    def _log(self,text):
        self.log_box.insert('end',text+'\n'); self.log_box.see('end')

    def refresh_history(self):
        if not hasattr(self,'history_tree'): return
        for item in self.history_tree.get_children(): self.history_tree.delete(item)
        query=self.search_entry.get() if hasattr(self,'search_entry') else ''
        for row in self.database.search(query):
            self.history_tree.insert('','end',values=(row['codigo_ticket'],row['usuario_desvinculado'],
                row['area_gerencia'],row['ruta_origen'],row['ruta_destino'],row['fecha_inicio'] or '',
                row['estado'],row['total_archivos'],row['archivos_fallidos']))

    def export_excel(self):
        path=filedialog.asksaveasfilename(defaultextension='.xlsx',
            filetypes=[('Libro de Excel','*.xlsx')],initialfile='historial_pasarelaBK.xlsx')
        if not path: return
        rows=self.database.search(self.search_entry.get())
        book=Workbook(); sheet=book.active; sheet.title='Historial'
        if rows:
            headers=list(rows[0]); sheet.append(headers)
            for row in rows: sheet.append([row.get(h) for h in headers])
        book.save(path)
        messagebox.showinfo('Exportación',f'Historial guardado en:\n{path}')
