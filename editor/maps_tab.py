import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_tile_template_keys, fetch_tile_set_names
from editor.tooltip import add_tooltip


class MapsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._list_names: list[str] = []
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)
        ttk.Label(left, text='Maps').pack(anchor='w')
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(lf, exportselection=False, width=22)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_map_select)
        br = ttk.Frame(left)
        br.pack(fill=tk.X, pady=4)
        btn_new = ttk.Button(br, text='New', command=self._new_map); btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new map')
        btn_save = ttk.Button(br, text='Save', command=self._save_map); btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current map to the database')
        btn_del = ttk.Button(br, text='Delete', command=self._delete_map); btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected map and its tile entries')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)
        f = right

        r = 0
        ttk.Label(f, text='Name').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_name = tk.StringVar()
        e_name = ttk.Entry(f, textvariable=self.v_name, width=22)
        e_name.grid(row=r, column=1, columnspan=3, sticky='ew', padx=6, pady=3)
        add_tooltip(e_name, 'Unique name for this map')
        r += 1

        ttk.Label(f, text='Tile Set').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_tile_set = tk.StringVar()
        self.tile_set_cb = ttk.Combobox(
            f, textvariable=self.v_tile_set,
            values=[''] + fetch_tile_set_names(), state='readonly', width=20)
        self.tile_set_cb.grid(row=r, column=1, columnspan=3, sticky='w', padx=6, pady=3)
        add_tooltip(self.tile_set_cb, 'Tile set used to build this map\'s floor layout')
        r += 1

        ttk.Label(f, text='Default Tile').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_default_tile_template = tk.StringVar()
        self.default_template_cb = ttk.Combobox(
            f, textvariable=self.v_default_tile_template,
            values=[''] + fetch_tile_template_keys(), state='readonly', width=20)
        self.default_template_cb.grid(row=r, column=1, columnspan=3, sticky='w', padx=6, pady=3)
        add_tooltip(self.default_template_cb, 'Tile template used to fill empty coordinates')
        r += 1

        ttk.Label(f, text='Entrance x,y').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_ent_x = tk.StringVar(value='0')
        self.v_ent_y = tk.StringVar(value='0')
        ent_x = ttk.Entry(f, textvariable=self.v_ent_x, width=6)
        ent_x.grid(row=r, column=1, sticky='w', padx=3, pady=3)
        add_tooltip(ent_x, 'X coordinate where the player spawns when entering')
        ent_y = ttk.Entry(f, textvariable=self.v_ent_y, width=6)
        ent_y.grid(row=r, column=2, sticky='w', padx=3, pady=3)
        add_tooltip(ent_y, 'Y coordinate where the player spawns when entering')
        r += 1

        axis_tips = {
            'w': 'World/layer dimension bounds',
            'x': 'Horizontal dimension bounds (map width)',
            'y': 'Vertical dimension bounds (map height)',
            'z': 'Elevation/floor dimension bounds',
        }
        for axis in ('w', 'x', 'y', 'z'):
            ttk.Label(f, text=f'{axis.upper()} min / max').grid(
                row=r, column=0, sticky='w', padx=6, pady=3)
            vmin = tk.StringVar(value='0')
            vmax = tk.StringVar(value='0')
            setattr(self, f'v_{axis}_min', vmin)
            setattr(self, f'v_{axis}_max', vmax)
            e_min = ttk.Entry(f, textvariable=vmin, width=6)
            e_min.grid(row=r, column=1, sticky='w', padx=3, pady=3)
            add_tooltip(e_min, f'{axis_tips[axis]} (minimum)')
            e_max = ttk.Entry(f, textvariable=vmax, width=6)
            e_max.grid(row=r, column=2, sticky='w', padx=3, pady=3)
            add_tooltip(e_max, f'{axis_tips[axis]} (maximum)')
            r += 1

        f.columnconfigure(1, weight=1)

    # ---- helpers ----------------------------------------------------------

    def _int_field(self, var, default=0):
        try:
            return int(var.get())
        except ValueError:
            return default

    def _current_map_name(self):
        sel = self.listbox.curselection()
        return self._list_names[sel[0]] if sel else None

    # ---- map list ---------------------------------------------------------

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name FROM maps ORDER BY name').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        self._list_names = [r['name'] for r in rows]
        for n in self._list_names:
            self.listbox.insert(tk.END, n)

    def refresh_tile_set_dropdown(self):
        self.tile_set_cb['values'] = [''] + fetch_tile_set_names()

    def _on_map_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._populate_map(self._list_names[sel[0]])

    def _populate_map(self, name: str):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM maps WHERE name=?', (name,)).fetchone()
        finally:
            con.close()
        if row is None:
            return
        self.v_name.set(row['name'])
        self.v_tile_set.set(row['tile_set'] or '')
        self.v_default_tile_template.set(row['default_tile_template'] or '')
        self.v_ent_x.set(str(row['entrance_x']))
        self.v_ent_y.set(str(row['entrance_y']))
        for axis in ('w', 'x', 'y', 'z'):
            getattr(self, f'v_{axis}_min').set(str(row[f'{axis}_min']))
            getattr(self, f'v_{axis}_max').set(str(row[f'{axis}_max']))
        self.default_template_cb['values'] = [''] + fetch_tile_template_keys()
        self.tile_set_cb['values'] = [''] + fetch_tile_set_names()

    def _clear_map_form(self):
        self.v_name.set('')
        self.v_tile_set.set('')
        self.v_default_tile_template.set('')
        self.v_ent_x.set('0')
        self.v_ent_y.set('0')
        for axis in ('w', 'x', 'y', 'z'):
            getattr(self, f'v_{axis}_min').set('0')
            getattr(self, f'v_{axis}_max').set('0')

    def _new_map(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_map_form()

    def _save_map(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name is required.')
            return
        ts = self.v_tile_set.get().strip() or None
        dt = self.v_default_tile_template.get().strip() or None
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO maps
                   (name, tile_set, default_tile_template, entrance_x, entrance_y,
                    w_min, w_max, x_min, x_max, y_min, y_max, z_min, z_max)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(name) DO UPDATE SET
                   tile_set=excluded.tile_set,
                   default_tile_template=excluded.default_tile_template,
                   entrance_x=excluded.entrance_x, entrance_y=excluded.entrance_y,
                   w_min=excluded.w_min, w_max=excluded.w_max,
                   x_min=excluded.x_min, x_max=excluded.x_max,
                   y_min=excluded.y_min, y_max=excluded.y_max,
                   z_min=excluded.z_min, z_max=excluded.z_max''',
                (name, ts, dt,
                 self._int_field(self.v_ent_x), self._int_field(self.v_ent_y),
                 self._int_field(self.v_w_min), self._int_field(self.v_w_max),
                 self._int_field(self.v_x_min), self._int_field(self.v_x_max),
                 self._int_field(self.v_y_min), self._int_field(self.v_y_max),
                 self._int_field(self.v_z_min), self._int_field(self.v_z_max)))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        if name in self._list_names:
            idx = self._list_names.index(name)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def _delete_map(self):
        name = self._current_map_name()
        if not name:
            messagebox.showwarning('Delete', 'Select a map first.')
            return
        if not messagebox.askyesno('Delete', f'Delete map "{name}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM maps WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_map_form()
