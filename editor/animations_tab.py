import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con, fetch_sprite_names, fetch_animation_names, fetch_species_names
from editor.constants import PREVIEW_SIZE
from editor.sprite_preview import SpritePreview
from editor.tooltip import add_tooltip

TARGET_TYPES = ['creature', 'tile', 'world_object']
BEHAVIORS = [
    'idle', 'idle_combat',
    'walk_north', 'walk_south', 'walk_east', 'walk_west',
    'attack_north', 'attack_south', 'attack_east', 'attack_west',
    'hurt', 'block', 'death',
    'activate', 'pickup', 'use_item', 'craft',
    'search', 'dig', 'crouch', 'stagger', 'prone',
]


class AnimationsTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._anim_names: list[str] = []
        self._frame_rows: list[dict] = []  # [{sprite_name, duration_ms}]
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # ---- left: animation list -------------------------------------------
        left = ttk.Frame(pane, width=180)
        pane.add(left, weight=0)
        ttk.Label(left, text='Animations').pack(anchor='w')
        lf = ttk.Frame(left)
        lf.pack(fill=tk.BOTH, expand=True)
        self.listbox = tk.Listbox(lf, exportselection=False, width=24)
        sb = ttk.Scrollbar(lf, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())
        br = ttk.Frame(left)
        br.pack(fill=tk.X, pady=4)
        btn_new = ttk.Button(br, text='New', command=self._new); btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new animation')
        btn_save = ttk.Button(br, text='Save', command=self._save); btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current animation to the database')
        btn_del = ttk.Button(br, text='Delete', command=self._delete); btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected animation')

        # ---- right: animation editor ----------------------------------------
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        # name + target type
        top = ttk.Frame(right)
        top.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(top, text='Name').pack(side=tk.LEFT)
        self.v_name = tk.StringVar()
        e_name = ttk.Entry(top, textvariable=self.v_name, width=24)
        e_name.pack(side=tk.LEFT, padx=6)
        add_tooltip(e_name, 'Unique animation name')
        ttk.Label(top, text='Type').pack(side=tk.LEFT, padx=(12, 0))
        self.v_type = tk.StringVar(value='creature')
        type_cb = ttk.Combobox(top, textvariable=self.v_type, values=TARGET_TYPES,
                     state='readonly', width=14)
        type_cb.pack(side=tk.LEFT, padx=4)
        add_tooltip(type_cb, 'What kind of object this animation targets')

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6, pady=4)

        # ---- animation preview ----------------------------------------------
        preview_row = ttk.Frame(right)
        preview_row.pack(fill=tk.X, padx=6, pady=4)

        self._anim_preview = SpritePreview(preview_row, size=PREVIEW_SIZE * 2)
        self._anim_preview.pack(side=tk.LEFT, padx=(0, 8))

        preview_ctrl = ttk.Frame(preview_row)
        preview_ctrl.pack(side=tk.LEFT, anchor='n')
        self._play_btn = ttk.Button(preview_ctrl, text='Play', command=self._toggle_preview)
        self._play_btn.pack(anchor='w', pady=2)
        add_tooltip(self._play_btn, 'Play/stop the animation preview')
        self._preview_label = ttk.Label(preview_ctrl, text='Stopped', foreground='#555')
        self._preview_label.pack(anchor='w', pady=2)

        self._preview_playing = False
        self._preview_frame_idx = 0
        self._preview_after_id = None

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6, pady=4)

        # ---- frames section -------------------------------------------------
        ttk.Label(right, text='Frames', font=('TkDefaultFont', 10, 'bold')).pack(
            anchor='w', padx=6)

        self._frames_container = ttk.Frame(right)
        self._frames_container.pack(fill=tk.BOTH, expand=True, padx=6, pady=2)

        # column headers
        hdr = ttk.Frame(self._frames_container)
        hdr.pack(fill=tk.X)
        ttk.Label(hdr, text='#', width=3).pack(side=tk.LEFT)
        ttk.Label(hdr, text='Sprite', width=18).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Duration (ms)', width=12).pack(side=tk.LEFT, padx=4)
        ttk.Label(hdr, text='Preview', width=8).pack(side=tk.LEFT, padx=4)

        self._frames_list_frame = ttk.Frame(self._frames_container)
        self._frames_list_frame.pack(fill=tk.BOTH, expand=True)
        add_tooltip(self._frames_list_frame, 'Animation frames in play order; select to edit')

        frame_btns = ttk.Frame(right)
        frame_btns.pack(fill=tk.X, padx=6, pady=4)
        add_frame_btn = ttk.Button(frame_btns, text='+ Add Frame', command=self._add_frame)
        add_frame_btn.pack(side=tk.LEFT, padx=2)
        add_tooltip(add_frame_btn, 'Append a new frame to this animation')

        ttk.Separator(right, orient=tk.HORIZONTAL).pack(fill=tk.X, padx=6, pady=4)

        # ---- bindings section -----------------------------------------------
        ttk.Label(right, text='Bindings', font=('TkDefaultFont', 10, 'bold')).pack(
            anchor='w', padx=6)

        bind_row = ttk.Frame(right)
        bind_row.pack(fill=tk.X, padx=6, pady=4)
        ttk.Label(bind_row, text='Target').pack(side=tk.LEFT)
        self.v_bind_target = tk.StringVar()
        self._bind_target_cb = ttk.Combobox(
            bind_row, textvariable=self.v_bind_target,
            values=fetch_species_names(), width=16)
        self._bind_target_cb.pack(side=tk.LEFT, padx=4)
        add_tooltip(self._bind_target_cb, 'Species or sprite name this animation applies to')
        ttk.Label(bind_row, text='Behavior').pack(side=tk.LEFT, padx=(8, 0))
        self.v_bind_behavior = tk.StringVar(value='idle')
        behav_cb = ttk.Combobox(bind_row, textvariable=self.v_bind_behavior,
                     values=BEHAVIORS, width=14)
        behav_cb.pack(side=tk.LEFT, padx=4)
        add_tooltip(behav_cb, 'Action that triggers this animation (idle, walk, attack, etc.)')
        add_bind_btn = ttk.Button(bind_row, text='Add Binding', command=self._add_binding)
        add_bind_btn.pack(side=tk.LEFT, padx=4)
        add_tooltip(add_bind_btn, 'Link this animation to the target + behavior pair')

        self._bindings_frame = ttk.Frame(right)
        self._bindings_frame.pack(fill=tk.X, padx=6, pady=2)

    # ---- list ---------------------------------------------------------------

    def refresh_list(self):
        con = get_con()
        try:
            rows = con.execute('SELECT name FROM animations ORDER BY name').fetchall()
        finally:
            con.close()
        self.listbox.delete(0, tk.END)
        self._anim_names = [r['name'] for r in rows]
        for n in self._anim_names:
            self.listbox.insert(tk.END, n)

    def refresh_dropdowns(self):
        self._bind_target_cb['values'] = fetch_species_names()

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        self._load_animation(self._anim_names[sel[0]])

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _clear_form(self):
        self._stop_preview()
        self.v_name.set('')
        self.v_type.set('creature')
        self._frame_rows = []
        self._rebuild_frame_widgets()
        self._rebuild_binding_widgets([])

    # ---- load ---------------------------------------------------------------

    def _load_animation(self, name: str):
        self._stop_preview()
        con = get_con()
        try:
            row = con.execute('SELECT * FROM animations WHERE name=?', (name,)).fetchone()
            if row is None:
                return
            self.v_name.set(row['name'])
            self.v_type.set(row['target_type'])

            frames = con.execute(
                'SELECT sprite_name, duration_ms FROM animation_frames'
                ' WHERE animation_name=? ORDER BY frame_index', (name,)
            ).fetchall()
            self._frame_rows = [
                {'sprite_name': f['sprite_name'], 'duration_ms': f['duration_ms']}
                for f in frames
            ]
            self._rebuild_frame_widgets()

            bindings = con.execute(
                'SELECT id, target_name, behavior FROM animation_bindings'
                ' WHERE animation_name=?', (name,)
            ).fetchall()
            self._rebuild_binding_widgets(bindings)
        finally:
            con.close()

    # ---- frames UI ----------------------------------------------------------

    def _rebuild_frame_widgets(self):
        for child in self._frames_list_frame.winfo_children():
            child.destroy()
        sprite_names = [''] + fetch_sprite_names()
        for i, fr in enumerate(self._frame_rows):
            row = ttk.Frame(self._frames_list_frame)
            row.pack(fill=tk.X, pady=1)

            ttk.Label(row, text=str(i), width=3).pack(side=tk.LEFT)

            sv = tk.StringVar(value=fr['sprite_name'])
            cb = ttk.Combobox(row, textvariable=sv, values=sprite_names,
                              state='readonly', width=16)
            cb.pack(side=tk.LEFT, padx=4)
            add_tooltip(cb, 'Sprite to display for this animation frame')

            dv = tk.StringVar(value=str(fr['duration_ms']))
            dur_entry = ttk.Entry(row, textvariable=dv, width=8)
            dur_entry.pack(side=tk.LEFT, padx=4)
            add_tooltip(dur_entry, 'How long this frame displays in milliseconds')

            preview = SpritePreview(row, size=PREVIEW_SIZE // 2)
            preview.pack(side=tk.LEFT, padx=4)
            preview.load(fr['sprite_name'] or None)

            def _on_sprite_change(e, idx=i, s=sv, p=preview):
                self._frame_rows[idx]['sprite_name'] = s.get()
                p.load(s.get() or None)
            cb.bind('<<ComboboxSelected>>', _on_sprite_change)

            def _on_dur_change(*args, idx=i, d=dv):
                try:
                    self._frame_rows[idx]['duration_ms'] = int(d.get())
                except ValueError:
                    pass
            dv.trace_add('write', _on_dur_change)

            # move up / move down / delete
            btn_frame = ttk.Frame(row)
            btn_frame.pack(side=tk.LEFT, padx=4)

            def _move_up(idx=i):
                if idx > 0:
                    self._frame_rows[idx-1], self._frame_rows[idx] = \
                        self._frame_rows[idx], self._frame_rows[idx-1]
                    self._rebuild_frame_widgets()
            def _move_down(idx=i):
                if idx < len(self._frame_rows) - 1:
                    self._frame_rows[idx], self._frame_rows[idx+1] = \
                        self._frame_rows[idx+1], self._frame_rows[idx]
                    self._rebuild_frame_widgets()
            def _remove(idx=i):
                self._frame_rows.pop(idx)
                self._rebuild_frame_widgets()

            btn_up = ttk.Button(btn_frame, text='\u25b2', width=2, command=_move_up); btn_up.pack(side=tk.LEFT)
            add_tooltip(btn_up, 'Move frame up in sequence')
            btn_down = ttk.Button(btn_frame, text='\u25bc', width=2, command=_move_down); btn_down.pack(side=tk.LEFT)
            add_tooltip(btn_down, 'Move frame down in sequence')
            btn_rm = ttk.Button(btn_frame, text='\u2715', width=2, command=_remove); btn_rm.pack(side=tk.LEFT)
            add_tooltip(btn_rm, 'Remove this frame')

    def _add_frame(self):
        self._frame_rows.append({'sprite_name': '', 'duration_ms': 150})
        self._rebuild_frame_widgets()

    # ---- bindings UI --------------------------------------------------------

    def _rebuild_binding_widgets(self, bindings):
        for child in self._bindings_frame.winfo_children():
            child.destroy()
        self._binding_ids = []
        for b in bindings:
            bid = b['id']
            self._binding_ids.append(bid)
            row = ttk.Frame(self._bindings_frame)
            row.pack(fill=tk.X, pady=1)
            ttk.Label(row, text=f"{b['target_name']} \u2192 {b['behavior']}").pack(
                side=tk.LEFT, padx=4)

            def _del_binding(binding_id=bid):
                self._delete_binding(binding_id)
            del_btn = ttk.Button(row, text='\u2715', width=2, command=_del_binding)
            del_btn.pack(side=tk.LEFT, padx=4)
            add_tooltip(del_btn, 'Remove this animation binding')

    def _add_binding(self):
        name = self.v_name.get().strip()
        target = self.v_bind_target.get().strip()
        behavior = self.v_bind_behavior.get().strip()
        if not name or not target or not behavior:
            messagebox.showerror('Validation', 'Animation name, target, and behavior are required.')
            return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO animation_bindings (target_name, behavior, animation_name)
                   VALUES (?, ?, ?)
                   ON CONFLICT(target_name, behavior) DO UPDATE SET
                   animation_name=excluded.animation_name''',
                (target, behavior, name))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        # Reload bindings display
        self._load_animation(name)

    def _delete_binding(self, binding_id: int):
        con = get_con()
        try:
            con.execute('DELETE FROM animation_bindings WHERE id=?', (binding_id,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        name = self.v_name.get().strip()
        if name:
            self._load_animation(name)

    # ---- save / delete ------------------------------------------------------

    def _save(self):
        name = self.v_name.get().strip()
        if not name:
            messagebox.showerror('Validation', 'Name is required.')
            return
        target_type = self.v_type.get().strip()

        con = get_con()
        try:
            con.execute(
                '''INSERT INTO animations (name, target_type) VALUES (?, ?)
                   ON CONFLICT(name) DO UPDATE SET target_type=excluded.target_type''',
                (name, target_type))

            # Replace all frames
            con.execute('DELETE FROM animation_frames WHERE animation_name=?', (name,))
            for i, fr in enumerate(self._frame_rows):
                sn = fr['sprite_name'].strip()
                if not sn:
                    continue
                con.execute(
                    'INSERT INTO animation_frames (animation_name, frame_index, sprite_name, duration_ms)'
                    ' VALUES (?, ?, ?, ?)',
                    (name, i, sn, fr['duration_ms']))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        if name in self._anim_names:
            idx = self._anim_names.index(name)
            self.listbox.selection_set(idx)
            self.listbox.see(idx)

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select an animation first.')
            return
        name = self._anim_names[sel[0]]
        if not messagebox.askyesno('Delete', f'Delete animation "{name}" and all its bindings?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM animation_bindings WHERE animation_name=?', (name,))
            con.execute('DELETE FROM animation_frames WHERE animation_name=?', (name,))
            con.execute('DELETE FROM animations WHERE name=?', (name,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()

    # ---- animation preview --------------------------------------------------

    def _toggle_preview(self):
        if self._preview_playing:
            self._stop_preview()
        else:
            self._start_preview()

    def _start_preview(self):
        valid = [f for f in self._frame_rows if f['sprite_name'].strip()]
        if not valid:
            return
        self._preview_playing = True
        self._preview_frame_idx = 0
        self._play_btn.configure(text='Stop')
        self._show_preview_frame()

    def _stop_preview(self):
        self._preview_playing = False
        if self._preview_after_id is not None:
            self.after_cancel(self._preview_after_id)
            self._preview_after_id = None
        self._play_btn.configure(text='Play')
        self._preview_label.configure(text='Stopped')
        self._anim_preview._draw_empty()

    def _show_preview_frame(self):
        valid = [f for f in self._frame_rows if f['sprite_name'].strip()]
        if not valid or not self._preview_playing:
            self._stop_preview()
            return
        idx = self._preview_frame_idx % len(valid)
        frame = valid[idx]
        self._anim_preview.load(frame['sprite_name'])
        self._preview_label.configure(
            text=f"Frame {idx}/{len(valid)}  {frame['sprite_name']}  ({frame['duration_ms']}ms)")
        self._preview_frame_idx = idx + 1
        self._preview_after_id = self.after(frame['duration_ms'], self._show_preview_frame)
