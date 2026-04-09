import json
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import (
    get_con, fetch_species_names, fetch_creature_keys, fetch_conversation_names,
)
from editor.tooltip import add_tooltip

SPEAKERS = ['npc', 'player']


class DialogueTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self.refresh_tree()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # -- Left: conversation selector + tree view --
        left = ttk.Frame(pane, width=300)
        pane.add(left, weight=1)

        # Conversation selector
        conv_frame = ttk.Frame(left)
        conv_frame.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(conv_frame, text='Conversation:').pack(side=tk.LEFT)
        self.v_conversation = tk.StringVar()
        self.conv_cb = ttk.Combobox(conv_frame, textvariable=self.v_conversation,
                                    values=[], width=20)
        self.conv_cb.pack(side=tk.LEFT, padx=4, fill=tk.X, expand=True)
        self.conv_cb.bind('<<ComboboxSelected>>', lambda e: self.refresh_tree())
        self.conv_cb.bind('<Return>', lambda e: self.refresh_tree())
        add_tooltip(self.conv_cb, 'Select or type a conversation tree name')

        # Tree view
        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True)

        self.tree = ttk.Treeview(tree_frame, columns=('speaker', 'text_preview'),
                                 show='tree headings', selectmode='browse')
        self.tree.heading('#0', text='ID')
        self.tree.heading('speaker', text='Speaker')
        self.tree.heading('text_preview', text='Text')
        self.tree.column('#0', width=60, minwidth=40)
        self.tree.column('speaker', width=60, minwidth=40)
        self.tree.column('text_preview', width=200, minwidth=100)

        tsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=tsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind('<<TreeviewSelect>>', self._on_tree_select)
        self.tree.bind('<Shift-Delete>', lambda e: self._delete_node())

        # Buttons under tree
        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        btn_root = ttk.Button(btn_row, text='+ Root', command=self._new_root)
        btn_root.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_root, 'Add a new root dialogue node to this conversation')
        btn_child = ttk.Button(btn_row, text='+ Child', command=self._new_child)
        btn_child.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_child, 'Add a child response under the selected node')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete_node)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected node and all its children')
        btn_save = ttk.Button(btn_row, text='Save Node', command=self._save_node)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save changes to the selected dialogue node')

        # -- Right: node edit form --
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        ttk.Label(f, text='Node ID:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_id = tk.StringVar()
        lbl_id = ttk.Label(f, textvariable=self.v_id, font=('TkFixedFont', 9))
        lbl_id.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        add_tooltip(lbl_id, 'Auto-generated unique ID for this dialogue node')
        row += 1

        ttk.Label(f, text='Speaker:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_speaker = tk.StringVar(value='npc')
        sp_cb = ttk.Combobox(f, textvariable=self.v_speaker, values=SPEAKERS,
                             state='readonly', width=10)
        sp_cb.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        add_tooltip(sp_cb, 'Who speaks this line: npc or player')
        row += 1

        ttk.Label(f, text='Species:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_species = tk.StringVar()
        self._species_names = [''] + fetch_species_names()
        self.species_cb = ttk.Combobox(f, textvariable=self.v_species,
                                       values=self._species_names, width=18)
        self.species_cb.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        add_tooltip(self.species_cb, 'Species filter (blank = any species)')
        row += 1

        ttk.Label(f, text='Creature:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_creature = tk.StringVar()
        self._creature_keys = [''] + fetch_creature_keys()
        self.creature_cb = ttk.Combobox(f, textvariable=self.v_creature,
                                        values=self._creature_keys, width=18)
        self.creature_cb.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        add_tooltip(self.creature_cb, 'Specific NPC filter (blank = generic for species)')
        row += 1

        ttk.Label(f, text='Text:').grid(row=row, column=0, sticky='nw', padx=6, pady=2)
        self.text_box = tk.Text(f, width=40, height=4, wrap=tk.WORD)
        self.text_box.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        add_tooltip(self.text_box, 'Dialogue text shown to the player')
        row += 1

        ttk.Label(f, text='Char Conditions:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_char_cond = tk.StringVar(value='{}')
        e_cc = ttk.Entry(f, textvariable=self.v_char_cond, width=40)
        e_cc.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        add_tooltip(e_cc, 'JSON: character stat/trait conditions, e.g. {"level_min": 5, "sex": "female"}')
        row += 1

        ttk.Label(f, text='World Conditions:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_world_cond = tk.StringVar(value='{}')
        e_wc = ttk.Entry(f, textvariable=self.v_world_cond, width=40)
        e_wc.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        add_tooltip(e_wc, 'JSON: world state conditions, e.g. {"time_of_day": "night"}')
        row += 1

        ttk.Label(f, text='Quest Conditions:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_quest_cond = tk.StringVar(value='{}')
        e_qc = ttk.Entry(f, textvariable=self.v_quest_cond, width=40)
        e_qc.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        add_tooltip(e_qc, 'JSON: quest state conditions, e.g. {"quest_name": "completed"}')
        row += 1

        ttk.Label(f, text='Behavior:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_behavior = tk.StringVar()
        e_beh = ttk.Entry(f, textvariable=self.v_behavior, width=30)
        e_beh.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        add_tooltip(e_beh, 'Interaction behavior triggered by this node (e.g. "trade", "attack", "flee")')
        row += 1

        ttk.Label(f, text='Effects:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_effects = tk.StringVar(value='{}')
        e_eff = ttk.Entry(f, textvariable=self.v_effects, width=40)
        e_eff.grid(row=row, column=1, sticky='ew', padx=6, pady=2)
        add_tooltip(e_eff, 'JSON: quest/status/inventory changes, e.g. {"give_item": "sword", "set_quest": "started"}')
        row += 1

        ttk.Label(f, text='Sort Order:').grid(row=row, column=0, sticky='w', padx=6, pady=2)
        self.v_sort = tk.StringVar(value='0')
        e_sort = ttk.Entry(f, textvariable=self.v_sort, width=6)
        e_sort.grid(row=row, column=1, sticky='w', padx=6, pady=2)
        add_tooltip(e_sort, 'Display order among sibling nodes (lower = first)')
        row += 1

        f.columnconfigure(1, weight=1)

    def refresh_tree(self):
        """Rebuild the tree view for the selected conversation."""
        self.tree.delete(*self.tree.get_children())

        # Refresh conversation list
        conv_names = fetch_conversation_names()
        self.conv_cb['values'] = conv_names

        conv = self.v_conversation.get().strip()
        if not conv:
            return

        con = get_con()
        try:
            rows = con.execute(
                'SELECT id, parent_id, speaker, text, sort_order'
                ' FROM dialogue WHERE conversation=?'
                ' ORDER BY sort_order, id',
                (conv,)
            ).fetchall()
        finally:
            con.close()

        # Build tree: parent_id → children
        nodes = {}
        roots = []
        for r in rows:
            nodes[r['id']] = r
            if r['parent_id'] is None:
                roots.append(r['id'])

        def _insert(parent_iid, node_id):
            r = nodes[node_id]
            preview = (r['text'] or '')[:60]
            iid = str(node_id)
            self.tree.insert(parent_iid, 'end', iid=iid, text=str(node_id),
                             values=(r['speaker'], preview))
            # Insert children
            children = [n for n in nodes.values() if n['parent_id'] == node_id]
            children.sort(key=lambda n: (n['sort_order'], n['id']))
            for child in children:
                _insert(iid, child['id'])

        for rid in roots:
            _insert('', rid)

    def refresh_dropdowns(self):
        self._species_names = [''] + fetch_species_names()
        self.species_cb['values'] = self._species_names
        self._creature_keys = [''] + fetch_creature_keys()
        self.creature_cb['values'] = self._creature_keys

    def _clear_form(self):
        self.v_id.set('')
        self.v_speaker.set('npc')
        self.v_species.set('')
        self.v_creature.set('')
        self.text_box.delete('1.0', tk.END)
        self.v_char_cond.set('{}')
        self.v_world_cond.set('{}')
        self.v_quest_cond.set('{}')
        self.v_behavior.set('')
        self.v_effects.set('{}')
        self.v_sort.set('0')

    def _on_tree_select(self, event=None):
        sel = self.tree.selection()
        if not sel:
            return
        node_id = int(sel[0])
        self._load_node(node_id)

    def _load_node(self, node_id: int):
        con = get_con()
        try:
            row = con.execute('SELECT * FROM dialogue WHERE id=?', (node_id,)).fetchone()
        finally:
            con.close()
        if row is None:
            return

        self.v_id.set(str(row['id']))
        self.v_speaker.set(row['speaker'] or 'npc')
        self.v_species.set(row['species'] or '')
        self.v_creature.set(row['creature_key'] or '')
        self.text_box.delete('1.0', tk.END)
        self.text_box.insert('1.0', row['text'] or '')
        self.v_char_cond.set(row['char_conditions'] or '{}')
        self.v_world_cond.set(row['world_conditions'] or '{}')
        self.v_quest_cond.set(row['quest_conditions'] or '{}')
        self.v_behavior.set(row['behavior'] or '')
        self.v_effects.set(row['effects'] or '{}')
        self.v_sort.set(str(row['sort_order'] or 0))

    def _new_root(self):
        conv = self.v_conversation.get().strip()
        if not conv:
            messagebox.showerror('Validation', 'Enter a conversation name first.')
            return
        con = get_con()
        try:
            cur = con.execute(
                'INSERT INTO dialogue (conversation, speaker, text) VALUES (?, ?, ?)',
                (conv, 'npc', '')
            )
            con.commit()
            new_id = cur.lastrowid
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_tree()
        self.tree.selection_set(str(new_id))
        self._load_node(new_id)

    def _new_child(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning('Add Child', 'Select a parent node first.')
            return
        parent_id = int(sel[0])
        conv = self.v_conversation.get().strip()

        # Alternate speaker: if parent is npc, child defaults to player
        con = get_con()
        try:
            parent = con.execute('SELECT speaker FROM dialogue WHERE id=?', (parent_id,)).fetchone()
            child_speaker = 'player' if (parent and parent['speaker'] == 'npc') else 'npc'
            cur = con.execute(
                'INSERT INTO dialogue (conversation, parent_id, speaker, text) VALUES (?, ?, ?, ?)',
                (conv, parent_id, child_speaker, '')
            )
            con.commit()
            new_id = cur.lastrowid
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_tree()
        # Expand parent and select new child
        self.tree.item(str(parent_id), open=True)
        self.tree.selection_set(str(new_id))
        self._load_node(new_id)

    def _save_node(self):
        node_id = self.v_id.get().strip()
        if not node_id:
            messagebox.showwarning('Save', 'No node selected.')
            return

        text = self.text_box.get('1.0', tk.END).strip()
        try:
            sort_order = int(self.v_sort.get())
        except ValueError:
            sort_order = 0

        con = get_con()
        try:
            con.execute(
                '''UPDATE dialogue SET
                   speaker=?, species=?, creature_key=?, text=?,
                   char_conditions=?, world_conditions=?, quest_conditions=?,
                   behavior=?, effects=?, sort_order=?
                   WHERE id=?''',
                (
                    self.v_speaker.get(),
                    self.v_species.get().strip() or None,
                    self.v_creature.get().strip() or None,
                    text,
                    self.v_char_cond.get().strip() or '{}',
                    self.v_world_cond.get().strip() or '{}',
                    self.v_quest_cond.get().strip() or '{}',
                    self.v_behavior.get().strip() or None,
                    self.v_effects.get().strip() or '{}',
                    sort_order,
                    int(node_id),
                )
            )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_tree()
        self.tree.selection_set(node_id)

    def _delete_node(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a node first.')
            return
        node_id = int(sel[0])
        if not messagebox.askyesno('Delete', f'Delete node {node_id} and all children?'):
            return

        # Collect all descendant IDs
        to_delete = []
        def _collect(nid):
            to_delete.append(nid)
            for child_iid in self.tree.get_children(str(nid)):
                _collect(int(child_iid))
        _collect(node_id)

        con = get_con()
        try:
            for did in reversed(to_delete):
                con.execute('DELETE FROM dialogue WHERE id=?', (did,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_tree()
        self._clear_form()
