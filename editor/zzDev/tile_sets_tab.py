import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names, fetch_tile_template_keys, fetch_map_names, fetch_animation_names
from editor.tooltip import add_tooltip


class TileSetsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._list_names: list[str] = []
        self._entry_ids:  list[int] = []
        self._entry_rows: list[dict] = []
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # --- Left: tile set list ---
        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)
        ttk.Label(left, text='Tile Sets').pack(anchor='w')
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(lf, exportselection=False, width=22)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_ts_select)
        br = ttk.Frame(left)
        br.pack(fill=tk.X, pady=4)
        btn_new = ttk.Button(br, text='New', command=self._new_tile_set); btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new tile set')
        btn_del = ttk.Button(br, text='Delete', command=self._delete_tile_set); btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected tile set and all its entries')

        nf = ttk.Frame(left)
        nf.pack(fill=tk.X, pady=2)
        ttk.Label(nf, text='Name').pack(side=tk.LEFT, padx=2)
        self.v_ts_name = tk.StringVar()
        ts_entry = ttk.Entry(nf, textvariable=self.v_ts_name, width=16)
        ts_entry.pack(side=tk.LEFT, padx=2)
        add_tooltip(ts_entry, 'Unique name for this tile set')
        ttk.Button(nf, text='Save', command=self._save_tile_set).pack(side=tk.LEFT, padx=2)

        # --- Right: scrollable entries ---
        ro = ttk.Frame(pane)
        pane.add(ro, weight=1)
        rc = tk.Canvas(ro, highlightthickness=0)
        rsb = ttk.Scrollbar(ro, orient=tk.VERTICAL, command=rc.yview)
        rc.configure(yscrollcommand=rsb.set)
        rsb.pack(side=tk.RIGHT, fill=tk.Y)
        rc.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        right = ttk.Frame(rc)
        win = rc.create_window((0, 0), window=right, anchor='nw')
        right.bind('<Configure>', lambda e: rc.configure(scrollregion=rc.bbox('all')))
        rc.bind('<Configure>', lambda e: rc.itemconfig(win, width=e.width))

        f = right

        # --- Entry list ---
        ttk.Label(f, text='Entries', font=('TkDefaultFont', 9, 'bold')).grid(
            row=0, column=0, columnspan=4, sticky='w', padx=6, pady=(8, 2))

        el_f = ttk.Frame(f)
        el_f.grid(row=1, column=0, columnspan=4, sticky='ew', padx=6, pady=4)
        self.entries_listbox = tk.Listbox(el_f, exportselection=False, height=10, width=55)
        el_sb = ttk.Scrollbar(el_f, orient=tk.VERTICAL, command=self.entries_listbox.yview)
        self.entries_listbox.configure(yscrollcommand=el_sb.set)
        self.entries_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        el_sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.entries_listbox.bind('<<ListboxSelect>>', self._on_entry_select)

        el_br = ttk.Frame(f)
        el_br.grid(row=2, column=0, columnspan=4, sticky='w', padx=6, pady=2)
        btn_rem = ttk.Button(el_br, text='Remove Selected', command=self._remove_entry); btn_rem.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_rem, 'Remove the selected tile entry from this set')
        btn_clr = ttk.Button(el_br, text='Clear Form', command=self._clear_entry_form); btn_clr.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_clr, 'Clear the entry form fields')

        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=3, column=0, columnspan=4, sticky='ew', padx=6, pady=6)
        ttk.Label(f, text='Add / Edit Entry', font=('TkDefaultFont', 9, 'bold')).grid(
            row=4, column=0, columnspan=4, sticky='w', padx=6, pady=(4, 2))

        r = 5
        for i, label in enumerate(('x', 'y', 'z')):
            ttk.Label(f, text=label.upper()).grid(
                row=r, column=i, padx=(6 if i == 0 else 2, 2), pady=3, sticky='w')
        r += 1
        self.v_x = tk.StringVar()
        self.v_y = tk.StringVar()
        self.v_z = tk.StringVar(value='0')
        coord_tips = ['X: horizontal position', 'Y: vertical position', 'Z: elevation/floor']
        for i, (v, tip) in enumerate(zip((self.v_x, self.v_y, self.v_z), coord_tips)):
            e = ttk.Entry(f, textvariable=v, width=6)
            e.grid(row=r, column=i, padx=(6 if i == 0 else 2, 2), pady=3, sticky='w')
            add_tooltip(e, tip)
        r += 1

        ttk.Label(f, text='Template').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_template = tk.StringVar()
        self.template_cb = ttk.Combobox(
            f, textvariable=self.v_template,
            values=[''] + fetch_tile_template_keys(), state='readonly', width=18)
        self.template_cb.grid(row=r, column=1, columnspan=3, sticky='w', padx=6, pady=3)
        add_tooltip(self.template_cb, 'Base tile template (provides defaults for walkable, sprite, etc.)')
        r += 1

        ttk.Label(f, text='Walkable override').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_walkable = tk.StringVar(value='(template)')
        walk_cb = ttk.Combobox(f, textvariable=self.v_walkable,
                     values=['(template)', 'walkable', 'blocked'],
                     state='readonly', width=14)
        walk_cb.grid(row=r, column=1, sticky='w', padx=6, pady=3)
        add_tooltip(walk_cb, 'Override walkability or inherit from template')
        r += 1

        ttk.Label(f, text='Covered override').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_covered = tk.StringVar(value='(template)')
        cov_cb = ttk.Combobox(f, textvariable=self.v_covered,
                     values=['(template)', 'yes', 'no'],
                     state='readonly', width=14)
        cov_cb.grid(row=r, column=1, sticky='w', padx=6, pady=3)
        add_tooltip(cov_cb, 'Override roof/ceiling status or inherit from template')
        r += 1

        ttk.Label(f, text='Sprite override').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_sprite = tk.StringVar()
        self.sprite_cb = ttk.Combobox(
            f, textvariable=self.v_sprite,
            values=[''] + fetch_sprite_names(), state='readonly', width=18)
        self.sprite_cb.grid(row=r, column=1, columnspan=3, sticky='w', padx=6, pady=3)
        add_tooltip(self.sprite_cb, 'Override sprite or leave blank to use template sprite')
        r += 1

        ttk.Label(f, text='Scale override').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_scale = tk.StringVar()
        scale_e = ttk.Entry(f, textvariable=self.v_scale, width=8)
        scale_e.grid(row=r, column=1, sticky='w', padx=6, pady=3)
        add_tooltip(scale_e, 'Override tile scale (blank = use template scale)')
        ttk.Label(f, text='(blank = template)').grid(
            row=r, column=2, sticky='w', padx=2, pady=3)
        r += 1

        ttk.Label(f, text='Nested Map').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_nested = tk.StringVar()
        self.nested_cb = ttk.Combobox(
            f, textvariable=self.v_nested,
            values=[''] + fetch_map_names(), state='readonly', width=18)
        self.nested_cb.grid(row=r, column=1, columnspan=3, sticky='w', padx=6, pady=3)
        add_tooltip(self.nested_cb, 'Map to enter when stepping on this tile')
        r += 1

        ttk.Label(f, text='Animation override').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_animation = tk.StringVar()
        self.anim_cb = ttk.Combobox(
            f, textvariable=self.v_animation,
            values=[''] + fetch_animation_names(), state='readonly', width=18)
        self.anim_cb.grid(row=r, column=1, columnspan=3, sticky='w', padx=6, pady=3)
        add_tooltip(self.anim_cb, 'Override tile animation (blank = use template animation)')
        r += 1

        # ---- Bounds overrides ----
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=r, column=0, columnspan=4, sticky='ew', padx=6, pady=6)
        r += 1
        ttk.Label(f, text='Bounds Override', font=('TkDefaultFont', 9, 'bold')).grid(
            row=r, column=0, columnspan=4, sticky='w', padx=6, pady=(4, 2))
        r += 1

        bound_values = ['', 'wall', 'opening', 'door_open', 'door_closed',
                        'gate_open', 'gate_closed']
        self._bound_vars = {}
        bound_pairs = [('n', 's'), ('e', 'w'), ('ne', 'nw'), ('se', 'sw')]
        for d1, d2 in bound_pairs:
            for j, d in enumerate((d1, d2)):
                var = tk.StringVar()
                self._bound_vars[d] = var
                ttk.Label(f, text=d.upper()).grid(row=r, column=j*2, sticky='w', padx=6, pady=2)
                cb = ttk.Combobox(f, textvariable=var, values=bound_values,
                                  state='readonly', width=12)
                cb.grid(row=r, column=j*2+1, sticky='w', padx=2, pady=2)
                add_tooltip(cb, f'{d.upper()} boundary override (blank = use template)')
            r += 1

        # ---- Warp fields ----
        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=r, column=0, columnspan=4, sticky='ew', padx=6, pady=6)
        r += 1
        ttk.Label(f, text='Warp', font=('TkDefaultFont', 9, 'bold')).grid(
            row=r, column=0, columnspan=4, sticky='w', padx=6, pady=(4, 2))
        r += 1

        ttk.Label(f, text='Warp Map').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_warp_map = tk.StringVar()
        self.warp_map_cb = ttk.Combobox(
            f, textvariable=self.v_warp_map,
            values=[''] + fetch_map_names(), state='readonly', width=18)
        self.warp_map_cb.grid(row=r, column=1, columnspan=3, sticky='w', padx=6, pady=3)
        add_tooltip(self.warp_map_cb, 'Target map to teleport to')
        r += 1

        ttk.Label(f, text='Warp X').grid(row=r, column=0, sticky='w', padx=6, pady=3)
        self.v_warp_x = tk.StringVar()
        wx_e = ttk.Entry(f, textvariable=self.v_warp_x, width=6)
        wx_e.grid(row=r, column=1, sticky='w', padx=6, pady=3)
        add_tooltip(wx_e, 'Target X coordinate (blank = map entrance)')
        ttk.Label(f, text='Warp Y').grid(row=r, column=2, sticky='w', padx=2, pady=3)
        self.v_warp_y = tk.StringVar()
        wy_e = ttk.Entry(f, textvariable=self.v_warp_y, width=6)
        wy_e.grid(row=r, column=3, sticky='w', padx=2, pady=3)
        add_tooltip(wy_e, 'Target Y coordinate (blank = map entrance)')
        r += 1

        self.v_warp_auto = tk.BooleanVar(value=False)
        warp_auto_cb = ttk.Checkbutton(f, text='Auto-warp (teleport on step)',
                                        variable=self.v_warp_auto)
        warp_auto_cb.grid(row=r, column=0, columnspan=4, sticky='w', padx=6, pady=3)
        add_tooltip(warp_auto_cb, 'If checked, teleport automatically when the player steps on this tile. Otherwise, requires Enter key.')
        r += 1

        btn_f = ttk.Frame(f)
        btn_f.grid(row=r, column=0, columnspan=4, sticky='w', padx=6, pady=6)
        add_btn = ttk.Button(btn_f, text='Add Entry', command=self._add_entry)
        add_btn.pack(side=tk.LEFT, padx=2)
        add_tooltip(add_btn, 'Add a new tile entry to this set')
        upd_btn = ttk.Button(btn_f, text='Update Selected', command=self._update_entry)
        upd_btn.pack(side=tk.LEFT, padx=2)
        add_tooltip(upd_btn, 'Overwrite the selected entry with current form values')

        f.columnconfigure(1, weight=1)
        f.columnconfigure(2, weight=1)

    def refresh_sprite_dropdown(self):
        self.sprite_cb['values'] = [''] + fetch_sprite_names()

    # ---- helpers ----------------------------------------------------------

    def _int_field(self, var, default=0):
        try:
            return int(var.get())
        except ValueError:
            return default

    def _current_ts_name(self):
        sel = self.listbox.curselection()
        return self._list_names[sel[0]] if sel else None

    # ---- tile set list ----------------------------------------------------

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name FROM tile_set_names').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        self._list_names = [r['name'] for r in rows]
        for n in self._list_names:
            self.listbox.insert(tk.END, n)

    def _on_ts_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        name = self._list_names[sel[0]]
        self.v_ts_name.set(name)
        self._populate_entries(name)

    def _populate_entries(self, ts_name: str):
        con = get_con()
        try:
            rows = con.execute(
                'SELECT * FROM tile_sets WHERE tile_set=? ORDER BY x,y,z',
                (ts_name,)
            ).fetchall()
        finally:
            con.close()
        self.template_cb['values'] = [''] + fetch_tile_template_keys()
        map_names = [''] + fetch_map_names()
        self.nested_cb['values'] = map_names
        self.warp_map_cb['values'] = map_names
        self.anim_cb['values'] = [''] + fetch_animation_names()
        self.entries_listbox.delete(0, tk.END)
        self._entry_ids = []
        self._entry_rows = []
        for r in rows:
            rd = dict(r)
            tmpl = rd.get('tile_template') or ''
            label = f"({rd['x']},{rd['y']},{rd['z']})  [{tmpl}]"
            if rd.get('sprite_name'):
                label += f"  sprite={rd['sprite_name']}"
            if rd.get('nested_map'):
                label += f"  nested={rd['nested_map']}"
            if rd.get('warp_map'):
                warp_lbl = f"  warp={rd['warp_map']}"
                if rd.get('warp_x') is not None:
                    warp_lbl += f"({rd['warp_x']},{rd['warp_y']})"
                if rd.get('warp_auto'):
                    warp_lbl += '[auto]'
                label += warp_lbl
            self.entries_listbox.insert(tk.END, label)
            self._entry_ids.append(rd['id'])
            self._entry_rows.append(rd)

    def _new_tile_set(self):
        self.listbox.selection_clear(0, tk.END)
        self.v_ts_name.set('')
        self.entries_listbox.delete(0, tk.END)
        self._entry_ids = []
        self._entry_rows = []
        self._clear_entry_form()

    def _save_tile_set(self):
        """Select/refresh the tile set by name. Names are derived from entries."""
        name = self.v_ts_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name is required.')
            return
        self.refresh_list()
        if name in self._list_names:
            idx = self._list_names.index(name)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)
            self._populate_entries(name)

    def _delete_tile_set(self):
        name = self._current_ts_name()
        if not name:
            messagebox.showwarning('Delete', 'Select a tile set first.')
            return
        if not messagebox.askyesno('Delete', f'Delete tile set "{name}" and all its entries?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM tile_sets WHERE tile_set=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._new_tile_set()

    # ---- entry form -------------------------------------------------------

    def _on_entry_select(self, event=None):
        sel = self.entries_listbox.curselection()
        if not sel:
            return
        r = self._entry_rows[sel[0]]
        self.v_x.set(str(r['x']))
        self.v_y.set(str(r['y']))
        self.v_z.set(str(r['z']))
        self.v_template.set(r['tile_template'] or '')
        if r['walkable'] is None:
            self.v_walkable.set('(template)')
        else:
            self.v_walkable.set('walkable' if r['walkable'] else 'blocked')
        if r['covered'] is None:
            self.v_covered.set('(template)')
        else:
            self.v_covered.set('yes' if r['covered'] else 'no')
        self.v_sprite.set(r['sprite_name'] or '')
        self.v_scale.set(str(r['tile_scale']) if r['tile_scale'] is not None else '')
        self.v_nested.set(r['nested_map'] or '')
        self.v_animation.set(r.get('animation_name') or '')
        for d in self._bound_vars:
            self._bound_vars[d].set(r.get(f'bounds_{d}') or '')
        self.v_warp_map.set(r.get('warp_map') or '')
        self.v_warp_x.set(str(r['warp_x']) if r.get('warp_x') is not None else '')
        self.v_warp_y.set(str(r['warp_y']) if r.get('warp_y') is not None else '')
        self.v_warp_auto.set(bool(r.get('warp_auto', 0)))

    def _clear_entry_form(self):
        self.v_x.set('')
        self.v_y.set('')
        self.v_z.set('0')
        self.v_template.set('')
        self.v_walkable.set('(template)')
        self.v_covered.set('(template)')
        self.v_sprite.set('')
        self.v_scale.set('')
        self.v_nested.set('')
        self.v_animation.set('')
        for var in self._bound_vars.values():
            var.set('')
        self.v_warp_map.set('')
        self.v_warp_x.set('')
        self.v_warp_y.set('')
        self.v_warp_auto.set(False)
        self.entries_listbox.selection_clear(0, tk.END)

    def _read_entry_form(self):
        try:
            x = int(self.v_x.get())
            y = int(self.v_y.get())
            z = self._int_field(self.v_z)
        except ValueError:
            messagebox.showerror('Validation', 'x, y, z must be integers.')
            return None
        tmpl = self.v_template.get().strip() or None
        sprite = self.v_sprite.get().strip() or None
        nested = self.v_nested.get().strip() or None
        walk_s = self.v_walkable.get()
        cov_s = self.v_covered.get()
        walkable = None if walk_s == '(template)' else (1 if walk_s == 'walkable' else 0)
        covered = None if cov_s == '(template)' else (1 if cov_s == 'yes' else 0)
        scale_s = self.v_scale.get().strip()
        scale = float(scale_s) if scale_s else None
        warp_map = self.v_warp_map.get().strip() or None
        warp_x_s = self.v_warp_x.get().strip()
        warp_x = int(warp_x_s) if warp_x_s else None
        warp_y_s = self.v_warp_y.get().strip()
        warp_y = int(warp_y_s) if warp_y_s else None
        warp_auto = 1 if self.v_warp_auto.get() else 0
        animation = self.v_animation.get().strip() or None
        bounds = {d: (self._bound_vars[d].get().strip() or None)
                  for d in ('n', 's', 'e', 'w', 'ne', 'nw', 'se', 'sw')}
        return dict(x=x, y=y, z=z, tile_template=tmpl, walkable=walkable,
                    covered=covered, sprite_name=sprite, tile_scale=scale, nested_map=nested,
                    animation_name=animation, bounds=bounds,
                    warp_map=warp_map, warp_x=warp_x, warp_y=warp_y, warp_auto=warp_auto)

    def _add_entry(self):
        name = self._current_ts_name()
        if not name:
            messagebox.showwarning('Add Entry', 'Save and select a tile set first.')
            return
        vals = self._read_entry_form()
        if vals is None:
            return
        con = get_con()
        try:
            b = vals['bounds']
            con.execute(
                '''INSERT INTO tile_sets
                   (tile_set, x, y, z, tile_template, walkable, covered,
                    sprite_name, tile_scale, nested_map, animation_name,
                    bounds_n, bounds_s, bounds_e, bounds_w,
                    bounds_ne, bounds_nw, bounds_se, bounds_sw,
                    warp_map, warp_x, warp_y, warp_auto)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (name, vals['x'], vals['y'], vals['z'],
                 vals['tile_template'], vals['walkable'], vals['covered'],
                 vals['sprite_name'], vals['tile_scale'], vals['nested_map'],
                 vals['animation_name'],
                 b['n'], b['s'], b['e'], b['w'],
                 b['ne'], b['nw'], b['se'], b['sw'],
                 vals['warp_map'], vals['warp_x'], vals['warp_y'], vals['warp_auto']))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self._populate_entries(name)

    def _update_entry(self):
        sel = self.entries_listbox.curselection()
        if not sel:
            messagebox.showwarning('Update', 'Select an entry first.')
            return
        entry_id = self._entry_ids[sel[0]]
        vals = self._read_entry_form()
        if vals is None:
            return
        con = get_con()
        try:
            b = vals['bounds']
            con.execute(
                '''UPDATE tile_sets SET
                   x=?, y=?, z=?, tile_template=?, walkable=?, covered=?,
                   sprite_name=?, tile_scale=?, nested_map=?, animation_name=?,
                   bounds_n=?, bounds_s=?, bounds_e=?, bounds_w=?,
                   bounds_ne=?, bounds_nw=?, bounds_se=?, bounds_sw=?,
                   warp_map=?, warp_x=?, warp_y=?, warp_auto=?
                   WHERE id=?''',
                (vals['x'], vals['y'], vals['z'], vals['tile_template'],
                 vals['walkable'], vals['covered'], vals['sprite_name'],
                 vals['tile_scale'], vals['nested_map'], vals['animation_name'],
                 b['n'], b['s'], b['e'], b['w'],
                 b['ne'], b['nw'], b['se'], b['sw'],
                 vals['warp_map'], vals['warp_x'], vals['warp_y'], vals['warp_auto'],
                 entry_id))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        name = self._current_ts_name()
        if name:
            self._populate_entries(name)
            if sel[0] < self.entries_listbox.size():
                self.entries_listbox.selection_set(sel[0])
                self.entries_listbox.see(sel[0])

    def _remove_entry(self):
        sel = self.entries_listbox.curselection()
        if not sel:
            messagebox.showwarning('Remove', 'Select an entry first.')
            return
        entry_id = self._entry_ids[sel[0]]
        con = get_con()
        try:
            con.execute('DELETE FROM tile_sets WHERE id=?', (entry_id,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        name = self._current_ts_name()
        if name:
            self._populate_entries(name)
