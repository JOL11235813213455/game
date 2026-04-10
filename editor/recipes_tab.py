"""Processing recipes editor tab.

Recipes describe single-step transformations: raw ingredients →
finished good. Each recipe has an output item (FK to items), an
output quantity, a category (food/material), a required tile
purpose, a stamina cost, and a list of ingredient items with
quantities stored in processing_recipe_inputs.
"""
import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox

from editor.db import get_con
from editor.tooltip import add_tooltip


_CATEGORIES = ('food', 'material')

# Must mirror actions.TILE_PURPOSES — we only list the purposes that
# could plausibly host a recipe station.
_TILE_PURPOSES = ('crafting', 'cooking', 'healing', 'training', 'farming',
                   'mining')


class RecipesTab(ttk.Frame):

    def __init__(self, parent):
        super().__init__(parent)
        self._item_keys: list[str] = []   # cached for comboboxes
        self._build_ui()
        self.refresh_list()

    def _build_ui(self):
        pane = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        left = ttk.Frame(pane, width=220)
        pane.add(left, weight=0)

        ttk.Label(left, text='Processing Recipes').pack(anchor='w')
        list_frame = ttk.Frame(left)
        list_frame.pack(fill=tk.BOTH, expand=True)

        self.listbox = tk.Listbox(list_frame, exportselection=False, width=28)
        sb = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        self.listbox.bind('<<ListboxSelect>>', self._on_select)
        self.listbox.bind('<Shift-Delete>', lambda e: self._delete())

        btn_row = ttk.Frame(left)
        btn_row.pack(fill=tk.X, pady=4)
        btn_new = ttk.Button(btn_row, text='New', command=self._new)
        btn_new.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_new, 'Clear form to create a new recipe')
        btn_save = ttk.Button(btn_row, text='Save', command=self._save)
        btn_save.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_save, 'Save the current recipe and its ingredient list')
        btn_del = ttk.Button(btn_row, text='Delete', command=self._delete)
        btn_del.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_del, 'Delete the selected recipe')

        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        f = right
        row = 0

        ttk.Label(f, text='Key').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_key = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_key, width=24)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4, columnspan=2)
        add_tooltip(e, 'Unique recipe identifier (e.g. bake_bread, smelt_iron)')
        row += 1

        ttk.Label(f, text='Name').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_name = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_name, width=24)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4, columnspan=2)
        add_tooltip(e, 'Display name (e.g. "Bake Bread")')
        row += 1

        ttk.Label(f, text='Description').grid(row=row, column=0, sticky='nw', padx=6, pady=4)
        self.v_description = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.v_description, width=48)
        e.grid(row=row, column=1, sticky='ew', padx=6, pady=4, columnspan=2)
        add_tooltip(e, 'Flavor text shown in the editor')
        row += 1

        ttk.Label(f, text='Category').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_category = tk.StringVar(value='food')
        cb = ttk.Combobox(f, textvariable=self.v_category, values=_CATEGORIES, width=12)
        cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(cb, 'food or material — used by PROCESS to filter')
        row += 1

        ttk.Label(f, text='Tile Purpose').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_tile_purpose = tk.StringVar(value='crafting')
        cb = ttk.Combobox(f, textvariable=self.v_tile_purpose,
                          values=_TILE_PURPOSES, width=14)
        cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(cb, 'Creature must stand on a tile with this purpose to run the recipe')
        row += 1

        ttk.Label(f, text='Stamina Cost').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_stamina = tk.StringVar(value='1')
        e = ttk.Entry(f, textvariable=self.v_stamina, width=8)
        e.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e, 'Stamina spent per execution')
        row += 1

        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=8)
        row += 1

        ttk.Label(f, text='Output Item').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_output = tk.StringVar()
        self.output_cb = ttk.Combobox(f, textvariable=self.v_output, values=[], width=28)
        self.output_cb.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(self.output_cb, 'Item produced by this recipe')
        row += 1

        ttk.Label(f, text='Output Qty').grid(row=row, column=0, sticky='w', padx=6, pady=4)
        self.v_output_qty = tk.StringVar(value='1')
        e = ttk.Entry(f, textvariable=self.v_output_qty, width=8)
        e.grid(row=row, column=1, sticky='w', padx=6, pady=4)
        add_tooltip(e, 'How many units the recipe produces per execution')
        row += 1

        ttk.Separator(f, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=3, sticky='ew', pady=8)
        row += 1

        ttk.Label(f, text='Ingredients').grid(row=row, column=0, sticky='nw', padx=6, pady=4)
        # Ingredients tree with item + quantity columns
        self.ing_tree = ttk.Treeview(f, columns=('qty',), show='tree headings', height=8)
        self.ing_tree.heading('#0', text='Item')
        self.ing_tree.heading('qty', text='Qty')
        self.ing_tree.column('#0', width=200)
        self.ing_tree.column('qty', width=60)
        self.ing_tree.grid(row=row, column=1, sticky='ew', padx=6, pady=4, columnspan=2)
        row += 1

        ing_row = ttk.Frame(f)
        ing_row.grid(row=row, column=1, sticky='w', padx=6, pady=4, columnspan=2)

        self.v_ing_item = tk.StringVar()
        self.ing_item_cb = ttk.Combobox(ing_row, textvariable=self.v_ing_item, values=[], width=24)
        self.ing_item_cb.pack(side=tk.LEFT, padx=2)
        add_tooltip(self.ing_item_cb, 'Select an item to add as an ingredient')

        self.v_ing_qty = tk.StringVar(value='1')
        ttk.Entry(ing_row, textvariable=self.v_ing_qty, width=5).pack(side=tk.LEFT, padx=2)

        btn_add = ttk.Button(ing_row, text='Add', command=self._add_ingredient)
        btn_add.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_add, 'Add this item+qty as an ingredient (select then Save to persist)')

        btn_rm = ttk.Button(ing_row, text='Remove', command=self._remove_ingredient)
        btn_rm.pack(side=tk.LEFT, padx=2)
        add_tooltip(btn_rm, 'Remove the selected ingredient row')
        row += 1

        f.columnconfigure(1, weight=1)

    def refresh_list(self):
        # Populate item comboboxes from DB
        con = get_con()
        try:
            self._item_keys = [r['key'] for r in con.execute(
                'SELECT key FROM items ORDER BY key').fetchall()]
            rows = con.execute(
                'SELECT key, name, output_item_key FROM processing_recipes '
                'ORDER BY key').fetchall()
        finally:
            con.close()
        self.output_cb['values'] = self._item_keys
        self.ing_item_cb['values'] = self._item_keys
        self.listbox.delete(0, tk.END)
        for r in rows:
            self.listbox.insert(tk.END, f"{r['key']}  → {r['output_item_key']}")

    def _clear_form(self):
        self.v_key.set('')
        self.v_name.set('')
        self.v_description.set('')
        self.v_category.set('food')
        self.v_tile_purpose.set('crafting')
        self.v_stamina.set('1')
        self.v_output.set('')
        self.v_output_qty.set('1')
        self.ing_tree.delete(*self.ing_tree.get_children())
        self.v_ing_item.set('')
        self.v_ing_qty.set('1')

    def _populate_form(self, key):
        con = get_con()
        try:
            row = con.execute(
                'SELECT * FROM processing_recipes WHERE key=?', (key,)
            ).fetchone()
            ings = con.execute(
                'SELECT ingredient_item_key, quantity FROM processing_recipe_inputs '
                'WHERE recipe_key=? ORDER BY id', (key,)
            ).fetchall()
        finally:
            con.close()
        if row is None:
            return
        self.v_key.set(row['key'])
        self.v_name.set(row['name'] or '')
        self.v_description.set(row['description'] or '')
        self.v_category.set(row['category'] or 'food')
        self.v_tile_purpose.set(row['required_tile_purpose'] or 'crafting')
        self.v_stamina.set(str(row['stamina_cost'] or 1))
        self.v_output.set(row['output_item_key'] or '')
        self.v_output_qty.set(str(row['output_quantity'] or 1))
        self.ing_tree.delete(*self.ing_tree.get_children())
        for ing in ings:
            self.ing_tree.insert('', tk.END, text=ing['ingredient_item_key'],
                                 values=(ing['quantity'],))

    def _on_select(self, event=None):
        sel = self.listbox.curselection()
        if not sel:
            return
        key = self.listbox.get(sel[0]).split('  ')[0]
        self._populate_form(key)

    def _add_ingredient(self):
        item_key = self.v_ing_item.get().strip()
        if not item_key:
            messagebox.showwarning('Ingredient', 'Select an item first.')
            return
        try:
            qty = int(self.v_ing_qty.get())
        except ValueError:
            messagebox.showerror('Ingredient', 'Quantity must be an integer.')
            return
        # Replace existing row for same item
        for iid in self.ing_tree.get_children():
            if self.ing_tree.item(iid, 'text') == item_key:
                self.ing_tree.delete(iid)
                break
        self.ing_tree.insert('', tk.END, text=item_key, values=(qty,))

    def _remove_ingredient(self):
        sel = self.ing_tree.selection()
        for iid in sel:
            self.ing_tree.delete(iid)

    def _new(self):
        self.listbox.selection_clear(0, tk.END)
        self._clear_form()

    def _save(self):
        key = self.v_key.get().strip()
        if not key:
            messagebox.showerror('Validation', 'Key is required.')
            return
        output = self.v_output.get().strip()
        if not output:
            messagebox.showerror('Validation', 'Output item is required.')
            return
        try:
            output_qty = int(self.v_output_qty.get())
            stamina = int(self.v_stamina.get())
        except ValueError:
            messagebox.showerror('Validation', 'Output qty and stamina must be integers.')
            return
        con = get_con()
        try:
            con.execute(
                '''INSERT INTO processing_recipes
                   (key, name, description, output_item_key, output_quantity,
                    category, required_tile_purpose, stamina_cost)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(key) DO UPDATE SET
                   name=excluded.name, description=excluded.description,
                   output_item_key=excluded.output_item_key,
                   output_quantity=excluded.output_quantity,
                   category=excluded.category,
                   required_tile_purpose=excluded.required_tile_purpose,
                   stamina_cost=excluded.stamina_cost
                ''',
                (key, self.v_name.get().strip(),
                 self.v_description.get().strip(), output, output_qty,
                 self.v_category.get().strip() or 'food',
                 self.v_tile_purpose.get().strip() or 'crafting',
                 stamina)
            )
            # Replace ingredient rows
            con.execute('DELETE FROM processing_recipe_inputs WHERE recipe_key=?', (key,))
            for iid in self.ing_tree.get_children():
                ing_key = self.ing_tree.item(iid, 'text')
                qty = int(self.ing_tree.item(iid, 'values')[0])
                con.execute(
                    'INSERT INTO processing_recipe_inputs '
                    '(recipe_key, ingredient_item_key, quantity) VALUES (?,?,?)',
                    (key, ing_key, qty)
                )
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()

    def _delete(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning('Delete', 'Select a recipe first.')
            return
        key = self.listbox.get(sel[0]).split('  ')[0]
        if not messagebox.askyesno('Delete', f'Delete recipe "{key}"?'):
            return
        con = get_con()
        try:
            con.execute('DELETE FROM processing_recipe_inputs WHERE recipe_key=?', (key,))
            con.execute('DELETE FROM processing_recipes WHERE key=?', (key,))
            con.commit()
        except sqlite3.Error as e:
            messagebox.showerror('DB Error', str(e))
            return
        finally:
            con.close()
        self.refresh_list()
        self._clear_form()
