import sqlite3
import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import time

from editor.db import get_con, DB_PATH
from editor.tooltip import add_tooltip


# ---------------------------------------------------------------------------
# SQLite cheat-sheet content (for MS SQL / Spark SQL users)
# ---------------------------------------------------------------------------

CHEATSHEET = r"""
# SQLite Quick Reference
## (for SQL Server / Spark SQL users)

─────────────────────────────────────────────
 DATA TYPES
─────────────────────────────────────────────
 SQLite has dynamic typing. Declared types are
 affinities, not constraints:

   INTEGER   — whole numbers (any size)
   REAL      — floating point
   TEXT      — UTF-8 string
   BLOB      — raw bytes
   NULL      — null

 There is NO: datetime, bit, varchar(n),
   nvarchar, decimal, money, uniqueidentifier

 Booleans: use INTEGER (0/1)
 Dates: store as TEXT ('2026-04-06') or
   INTEGER (unix epoch)

─────────────────────────────────────────────
 KEY DIFFERENCES FROM SQL SERVER
─────────────────────────────────────────────
 SQL Server              │ SQLite
 ────────────────────────┼──────────────────
 TOP N                   │ LIMIT N
 GETDATE()               │ datetime('now')
 ISNULL(a, b)            │ IFNULL(a, b)
                         │   or COALESCE(a, b)
 CAST(x AS INT)          │ CAST(x AS INTEGER)
 LEN(s)                  │ LENGTH(s)
 CHARINDEX(sub, s)       │ INSTR(s, sub)
                         │   (args reversed!)
 STUFF()                 │ no equivalent
 STRING_AGG(col, ',')    │ GROUP_CONCAT(col,',')
 IDENTITY                │ INTEGER PRIMARY KEY
                         │   (auto-increment)
 IF EXISTS ... DROP       │ DROP TABLE IF EXISTS
 ALTER TABLE DROP COLUMN │ not supported
 ALTER TABLE ALTER COLUMN│ not supported
 Multiple ALTER in one   │ one ALTER per
   statement             │   statement
 RIGHT JOIN              │ not supported
 FULL OUTER JOIN         │ not supported
                         │   (use UNION of LEFTs)
 MERGE                   │ INSERT ... ON CONFLICT
 UPDATE ... FROM         │ supported (3.33+)
 TRUNCATE TABLE          │ DELETE FROM table

─────────────────────────────────────────────
 KEY DIFFERENCES FROM SPARK SQL
─────────────────────────────────────────────
 Spark SQL               │ SQLite
 ────────────────────────┼──────────────────
 SHOW TABLES             │ .tables (CLI) or
                         │   SELECT name FROM
                         │   sqlite_master WHERE
                         │   type='table'
 DESCRIBE table          │ PRAGMA table_info(t)
 EXPLODE / LATERAL VIEW  │ not supported
 ARRAY / MAP / STRUCT    │ not supported
                         │   (use JSON functions)
 DISTRIBUTE BY / SORT BY │ not applicable
 PARTITION BY (DDL)      │ not supported
 Window functions        │ fully supported
 Common Table Expressions│ fully supported
 PIVOT / UNPIVOT         │ not built-in
                         │   (use CASE)

─────────────────────────────────────────────
 PRAGMAS (SQLite-specific)
─────────────────────────────────────────────
 PRAGMA table_info('t')  — column names/types
 PRAGMA foreign_keys=ON  — enable FK checks
 PRAGMA index_list('t')  — indexes on table
 PRAGMA database_list    — attached databases
 PRAGMA integrity_check  — verify DB health
 PRAGMA journal_mode     — WAL, DELETE, etc.

─────────────────────────────────────────────
 USEFUL SQLITE FUNCTIONS
─────────────────────────────────────────────
 typeof(x)              — returns type name
 json_extract(j, '$.k') — read JSON field
 json_group_array(col)  — aggregate to JSON []
 json_group_object(k,v) — aggregate to JSON {}
 printf('%d', x)        — formatted string
 substr(s, start, len)  — substring
 replace(s, from, to)   — string replace
 trim(s) / ltrim / rtrim— whitespace trim
 abs(x) / max() / min() — math
 random()               — random integer
 hex(x) / unhex(x)      — hex encode/decode
 zeroblob(n)            — n zero bytes

─────────────────────────────────────────────
 COMMON PATTERNS
─────────────────────────────────────────────
 -- Upsert (insert or update)
 INSERT INTO t (key, val) VALUES ('a', 1)
   ON CONFLICT(key) DO UPDATE
   SET val = excluded.val;

 -- Check if table exists
 SELECT name FROM sqlite_master
   WHERE type='table' AND name='mytable';

 -- List all columns
 PRAGMA table_info('mytable');

 -- Auto-increment primary key
 CREATE TABLE t (
   id INTEGER PRIMARY KEY AUTOINCREMENT,
   name TEXT NOT NULL
 );

 -- JSON in SQLite
 SELECT json_extract(data, '$.name')
   FROM t WHERE json_extract(data, '$.age') > 21;

 -- Window function
 SELECT name, value,
   ROW_NUMBER() OVER (ORDER BY value DESC) rn
 FROM t;

 -- CTE (Common Table Expression)
 WITH ranked AS (
   SELECT *, ROW_NUMBER() OVER (
     PARTITION BY category ORDER BY score DESC
   ) AS rn FROM items
 )
 SELECT * FROM ranked WHERE rn = 1;
"""


class SqlTab(ttk.Frame):
    """SQL editor tab with schema browser, query editor, and results pane."""

    def __init__(self, parent):
        super().__init__(parent)
        self._build_ui()
        self._refresh_schema()

    def _build_ui(self):
        notebook = ttk.Notebook(self)
        notebook.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Sub-tab 1: Query Editor
        editor_frame = ttk.Frame(notebook)
        notebook.add(editor_frame, text='  Query Editor  ')
        self._build_editor(editor_frame)

        # Sub-tab 2: ERD
        erd_frame = ttk.Frame(notebook)
        notebook.add(erd_frame, text='  ERD  ')
        self._build_erd(erd_frame)

        # Sub-tab 3: Data Dictionary
        dict_frame = ttk.Frame(notebook)
        notebook.add(dict_frame, text='  Data Dictionary  ')
        self._build_data_dictionary(dict_frame)

        # Sub-tab 4: Cheat Sheet
        cheat_frame = ttk.Frame(notebook)
        notebook.add(cheat_frame, text='  SQLite Cheat Sheet  ')
        self._build_cheatsheet(cheat_frame)

    # ------------------------------------------------------------------
    # Query Editor sub-tab
    # ------------------------------------------------------------------

    def _build_editor(self, parent):
        pane = ttk.PanedWindow(parent, orient=tk.HORIZONTAL)
        pane.pack(fill=tk.BOTH, expand=True, padx=2, pady=2)

        # ---- LEFT: Schema browser ----
        left = ttk.Frame(pane, width=220)
        pane.add(left, weight=0)

        lbl_f = ttk.Frame(left)
        lbl_f.pack(fill=tk.X)
        ttk.Label(lbl_f, text='Schema', font=('TkDefaultFont', 9, 'bold')).pack(
            side=tk.LEFT, padx=4, pady=(4, 2))
        refresh_btn = ttk.Button(lbl_f, text='\u21bb', width=3,
                                  command=self._refresh_schema)
        refresh_btn.pack(side=tk.RIGHT, padx=4, pady=(4, 2))
        add_tooltip(refresh_btn, 'Refresh schema tree')

        tree_frame = ttk.Frame(left)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self._schema_tree = ttk.Treeview(tree_frame, show='tree',
                                          selectmode='browse')
        schema_sb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                   command=self._schema_tree.yview)
        self._schema_tree.configure(yscrollcommand=schema_sb.set)
        self._schema_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        schema_sb.pack(side=tk.RIGHT, fill=tk.Y)
        add_tooltip(self._schema_tree,
                    'Database tables and columns. Double-click a table to insert its name, '
                    'double-click a column to insert "table.column"')
        self._schema_tree.bind('<Double-1>', self._on_schema_double_click)

        # ---- RIGHT: Editor + Results ----
        right = ttk.Frame(pane)
        pane.add(right, weight=1)

        vpane = ttk.PanedWindow(right, orient=tk.VERTICAL)
        vpane.pack(fill=tk.BOTH, expand=True)

        # -- Top: query editor --
        top = ttk.Frame(vpane)
        vpane.add(top, weight=1)

        toolbar = ttk.Frame(top)
        toolbar.pack(fill=tk.X, pady=(2, 0))

        run_btn = ttk.Button(toolbar, text='\u25b6 Run (Ctrl+Enter)',
                              command=self._run_query)
        run_btn.pack(side=tk.LEFT, padx=4, pady=2)
        add_tooltip(run_btn, 'Execute the SQL query (Ctrl+Enter)')

        clear_btn = ttk.Button(toolbar, text='Clear', command=self._clear_query)
        clear_btn.pack(side=tk.LEFT, padx=2, pady=2)
        add_tooltip(clear_btn, 'Clear the query editor')

        self._status_var = tk.StringVar(value='Ready')
        status_lbl = ttk.Label(toolbar, textvariable=self._status_var,
                                foreground='#666')
        status_lbl.pack(side=tk.RIGHT, padx=6, pady=2)

        editor_frame = ttk.Frame(top)
        editor_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        # Use a monospace font for the query editor
        mono = tkfont.Font(family='Courier', size=10)

        self._query_text = tk.Text(editor_frame, height=8, font=mono,
                                    wrap=tk.WORD, undo=True,
                                    bg='#1e1e1e', fg='#d4d4d4',
                                    insertbackground='#fff',
                                    selectbackground='#264f78',
                                    selectforeground='#fff',
                                    padx=6, pady=4)
        query_sb = ttk.Scrollbar(editor_frame, orient=tk.VERTICAL,
                                  command=self._query_text.yview)
        self._query_text.configure(yscrollcommand=query_sb.set)
        self._query_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        query_sb.pack(side=tk.RIGHT, fill=tk.Y)
        add_tooltip(self._query_text,
                    'Type SQL here. Ctrl+Enter to run. '
                    'Supports SELECT, INSERT, UPDATE, DELETE, PRAGMA, etc.')

        # Bind Ctrl+Enter to run
        self._query_text.bind('<Control-Return>', lambda e: self._run_query())
        self._query_text.bind('<Control-KP_Enter>', lambda e: self._run_query())

        # Insert starter text
        self._query_text.insert('1.0', 'SELECT name FROM sqlite_master WHERE type=\'table\' ORDER BY name;')

        # -- Bottom: results --
        bottom = ttk.Frame(vpane)
        vpane.add(bottom, weight=1)

        results_toolbar = ttk.Frame(bottom)
        results_toolbar.pack(fill=tk.X, pady=(2, 0))
        ttk.Label(results_toolbar, text='Results',
                   font=('TkDefaultFont', 9, 'bold')).pack(
            side=tk.LEFT, padx=6, pady=2)

        self._rows_var = tk.StringVar(value='')
        ttk.Label(results_toolbar, textvariable=self._rows_var,
                   foreground='#666').pack(side=tk.RIGHT, padx=6, pady=2)

        export_btn = ttk.Button(results_toolbar, text='Copy TSV',
                                 command=self._copy_results_tsv)
        export_btn.pack(side=tk.RIGHT, padx=2, pady=2)
        add_tooltip(export_btn, 'Copy results to clipboard as tab-separated values')

        results_frame = ttk.Frame(bottom)
        results_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=2)

        self._results_tree = ttk.Treeview(results_frame, show='headings',
                                           selectmode='extended')
        results_xsb = ttk.Scrollbar(results_frame, orient=tk.HORIZONTAL,
                                     command=self._results_tree.xview)
        results_ysb = ttk.Scrollbar(results_frame, orient=tk.VERTICAL,
                                     command=self._results_tree.yview)
        self._results_tree.configure(xscrollcommand=results_xsb.set,
                                      yscrollcommand=results_ysb.set)
        self._results_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        results_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        results_xsb.pack(side=tk.BOTTOM, fill=tk.X)

        # Error display (hidden by default)
        self._error_text = tk.Text(bottom, height=3, fg='#ff4444',
                                    bg='#2d1e1e', font=mono,
                                    wrap=tk.WORD, padx=6, pady=4)
        # Not packed initially — shown on error

    # ------------------------------------------------------------------
    # ERD sub-tab
    # ------------------------------------------------------------------

    def _build_erd(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=2)
        refresh_btn = ttk.Button(toolbar, text='\u21bb Refresh',
                                  command=self._draw_erd)
        refresh_btn.pack(side=tk.LEFT, padx=4, pady=2)
        add_tooltip(refresh_btn, 'Regenerate ERD from current database schema')

        self._erd_canvas = tk.Canvas(parent, bg='#1e1e1e',
                                      highlightthickness=0)
        erd_xsb = ttk.Scrollbar(parent, orient=tk.HORIZONTAL,
                                  command=self._erd_canvas.xview)
        erd_ysb = ttk.Scrollbar(parent, orient=tk.VERTICAL,
                                  command=self._erd_canvas.yview)
        self._erd_canvas.configure(xscrollcommand=erd_xsb.set,
                                    yscrollcommand=erd_ysb.set)
        erd_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        erd_xsb.pack(side=tk.BOTTOM, fill=tk.X)
        self._erd_canvas.pack(fill=tk.BOTH, expand=True)

        # Enable mouse wheel scrolling
        self._erd_canvas.bind('<MouseWheel>',
            lambda e: self._erd_canvas.yview_scroll(-1*(e.delta//120), 'units'))
        self._erd_canvas.bind('<Shift-MouseWheel>',
            lambda e: self._erd_canvas.xview_scroll(-1*(e.delta//120), 'units'))
        # Linux scroll
        self._erd_canvas.bind('<Button-4>',
            lambda e: self._erd_canvas.yview_scroll(-3, 'units'))
        self._erd_canvas.bind('<Button-5>',
            lambda e: self._erd_canvas.yview_scroll(3, 'units'))

        self.after(100, self._draw_erd)

    # Known soft FK relationships (no formal PRAGMA constraint)
    _SOFT_FKS = [
        ('maps', 'tile_set', 'tile_sets', 'tile_set'),
        ('maps', 'default_tile_template', 'tile_templates', 'key'),
        ('tile_sets', 'tile_template', 'tile_templates', 'key'),
        ('tile_sets', 'nested_map', 'maps', 'name'),
        ('tile_sets', 'linked_map', 'maps', 'name'),
        ('items', 'nested_map', 'maps', 'name'),
    ]

    # Clusters: groups of related tables laid out together
    _CLUSTERS = [
        {
            'label': 'Graphics',
            'color': '#1a3a1a',
            'tables': ['sprites', 'animations', 'animation_frames',
                        'animation_bindings'],
        },
        {
            'label': 'Composites',
            'color': '#1a1a3a',
            'tables': ['composite_sprites', 'composite_layers',
                        'layer_connections', 'layer_variants',
                        'composite_animations', 'composite_anim_keyframes',
                        'composite_anim_bindings'],
        },
        {
            'label': 'World',
            'color': '#3a2a1a',
            'tables': ['tile_templates', 'tile_sets', 'maps'],
        },
        {
            'label': 'Creatures',
            'color': '#2a1a2a',
            'tables': ['species', 'species_stats'],
        },
        {
            'label': 'Items',
            'color': '#1a2a2a',
            'tables': ['items', 'item_slots'],
        },
    ]

    def _draw_erd(self):
        canvas = self._erd_canvas
        canvas.delete('all')

        con = get_con()
        try:
            tables_raw = [r['name'] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name != 'sqlite_sequence' ORDER BY name").fetchall()]

            table_info = {}
            table_fks = {}
            for t in tables_raw:
                cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
                table_info[t] = [(c['name'], c['type'], c['pk'], c['notnull'],
                                   c['dflt_value']) for c in cols]
                fks = con.execute(f'PRAGMA foreign_key_list("{t}")').fetchall()
                table_fks[t] = [(fk['from'], fk['table'], fk['to']) for fk in fks]
        finally:
            con.close()

        # Merge soft FKs
        all_fk_cols = {}  # table → set of FK column names
        for t in tables_raw:
            all_fk_cols[t] = {fk[0] for fk in table_fks.get(t, [])}
        for src_t, src_c, dst_t, dst_c in self._SOFT_FKS:
            if src_t in table_info and dst_t in table_info:
                table_fks.setdefault(src_t, []).append((src_c, dst_t, dst_c))
                all_fk_cols.setdefault(src_t, set()).add(src_c)

        if not table_info:
            return

        # Layout parameters
        pad_x, pad_y = 40, 40
        cluster_pad = 20
        cluster_gap = 50
        inner_gap_x = 30
        inner_gap_y = 25
        box_pad = 8
        line_h = 16
        header_h = 22
        char_w = 7.5
        cluster_header_h = 28

        # Compute box sizes
        box_sizes = {}
        for t in table_info:
            cols = table_info[t]
            lines = []
            for cname, ctype, pk, nn, dflt in cols:
                prefix = 'PK ' if pk else '   '
                line = f'{prefix}{cname} ({ctype})'
                lines.append(line)
            max_line = max(len(t) + 4, *(len(l) for l in lines)) if lines else len(t) + 4
            w = int(max_line * char_w) + box_pad * 2
            h = header_h + len(cols) * line_h + box_pad * 2
            box_sizes[t] = (w, h, lines)

        # Lay out clusters
        positions = {}
        cluster_rects = []
        assigned = set()
        cur_cluster_y = pad_y

        for cluster in self._CLUSTERS:
            ctables = [t for t in cluster['tables'] if t in table_info]
            if not ctables:
                continue
            assigned.update(ctables)

            # Layout tables within cluster: 2-3 columns
            cols_in_cluster = min(3, len(ctables))
            rows_in_cluster = (len(ctables) + cols_in_cluster - 1) // cols_in_cluster

            # Compute column widths within cluster
            c_col_widths = [0] * cols_in_cluster
            c_row_heights = [0] * rows_in_cluster
            for i, t in enumerate(ctables):
                ci = i % cols_in_cluster
                ri = i // cols_in_cluster
                w, h, _ = box_sizes[t]
                c_col_widths[ci] = max(c_col_widths[ci], w)
                c_row_heights[ri] = max(c_row_heights[ri], h)

            # Place tables
            cx = pad_x + cluster_pad
            cy = cur_cluster_y + cluster_header_h + cluster_pad
            for i, t in enumerate(ctables):
                ci = i % cols_in_cluster
                ri = i // cols_in_cluster
                tx = cx + sum(c_col_widths[:ci]) + ci * inner_gap_x
                ty = cy + sum(c_row_heights[:ri]) + ri * inner_gap_y
                positions[t] = (tx, ty)

            # Cluster bounding box
            total_w = sum(c_col_widths) + (cols_in_cluster - 1) * inner_gap_x + cluster_pad * 2
            total_h = (sum(c_row_heights) + (rows_in_cluster - 1) * inner_gap_y
                       + cluster_pad * 2 + cluster_header_h)
            cluster_rects.append((
                pad_x, cur_cluster_y,
                pad_x + total_w, cur_cluster_y + total_h,
                cluster['label'], cluster['color']))
            cur_cluster_y += total_h + cluster_gap

        # Place any unassigned tables at the bottom
        unassigned = [t for t in table_info if t not in assigned]
        if unassigned:
            cx = pad_x + cluster_pad
            for t in unassigned:
                w, h, _ = box_sizes[t]
                positions[t] = (cx, cur_cluster_y)
                cx += w + inner_gap_x

        # Colors
        header_bg = '#264f78'
        header_fg = '#ffffff'
        body_bg = '#2d2d2d'
        body_fg = '#d4d4d4'
        pk_fg = '#dcdcaa'
        fk_fg = '#4ec9b0'
        line_color = '#569cd6'
        soft_line_color = '#888888'

        # Draw cluster backgrounds
        for cx1, cy1, cx2, cy2, label, color in cluster_rects:
            canvas.create_rectangle(cx1, cy1, cx2, cy2,
                                     fill=color, outline='#444', width=1,
                                     dash=(4, 2))
            canvas.create_text(cx1 + 10, cy1 + cluster_header_h // 2,
                                text=label, fill='#999',
                                font=('Courier', 10, 'bold'), anchor='w')

        # Draw table boxes
        col_positions = {}
        for t in table_info:
            if t not in positions:
                continue
            x, y = positions[t]
            w, h, lines = box_sizes[t]
            cols = table_info[t]
            fk_cols_set = all_fk_cols.get(t, set())

            canvas.create_rectangle(x, y, x + w, y + h,
                                     fill=body_bg, outline='#555', width=1)
            canvas.create_rectangle(x, y, x + w, y + header_h,
                                     fill=header_bg, outline='#555', width=1)
            canvas.create_text(x + w // 2, y + header_h // 2,
                                text=t, fill=header_fg,
                                font=('Courier', 9, 'bold'))

            for j, (cname, ctype, pk, nn, dflt) in enumerate(cols):
                cy = y + header_h + box_pad + j * line_h
                if pk:
                    prefix = 'PK '
                    color = pk_fg
                elif cname in fk_cols_set:
                    prefix = 'FK '
                    color = fk_fg
                else:
                    prefix = '   '
                    color = body_fg
                canvas.create_text(x + box_pad, cy,
                                    text=f'{prefix}{cname}',
                                    fill=color, anchor='w',
                                    font=('Courier', 8))
                canvas.create_text(x + w - box_pad, cy,
                                    text=ctype, fill='#888',
                                    anchor='e', font=('Courier', 8))
                col_positions[(t, cname)] = (x + w, cy)
                col_positions[(t, cname, 'left')] = (x, cy)

        # Build set of formal FK tuples for color distinction
        formal_fk_set = set()
        for t in tables_raw:
            fks_raw = con if False else []  # already collected above
        # Re-derive formal FKs from original pragma data
        _formal = set()
        con2 = get_con()
        try:
            for t in tables_raw:
                for fk in con2.execute(f'PRAGMA foreign_key_list("{t}")').fetchall():
                    _formal.add((t, fk['from'], fk['table'], fk['to']))
        finally:
            con2.close()

        # Draw relationship lines
        for t in table_info:
            for from_col, to_table, to_col in table_fks.get(t, []):
                if to_table not in positions or t not in positions:
                    continue
                src = col_positions.get((t, from_col))
                dst = col_positions.get((to_table, to_col, 'left'))
                if not dst:
                    dst_pos = positions.get(to_table)
                    if dst_pos:
                        dst = (dst_pos[0], dst_pos[1] + header_h // 2)
                if not src or not dst:
                    continue

                sx, sy = src
                dx, dy = dst

                is_formal = (t, from_col, to_table, to_col) in _formal
                lcolor = line_color if is_formal else soft_line_color
                ldash = () if is_formal else (6, 3)

                mid_x = (sx + dx) / 2
                canvas.create_line(sx, sy, mid_x, sy, mid_x, dy, dx, dy,
                                    fill=lcolor, width=1, smooth=True,
                                    arrow=tk.LAST, arrowshape=(8, 10, 4),
                                    dash=ldash)
                canvas.create_text(sx + 4, sy - 8, text='N',
                                    fill=lcolor, font=('Courier', 7),
                                    anchor='w')
                canvas.create_text(dx - 4, dy - 8, text='1',
                                    fill=lcolor, font=('Courier', 7),
                                    anchor='e')

        # Update scroll region
        all_items = canvas.bbox('all')
        if all_items:
            canvas.configure(scrollregion=(
                all_items[0] - 20, all_items[1] - 20,
                all_items[2] + 40, all_items[3] + 40))

    # ------------------------------------------------------------------
    # Data Dictionary sub-tab
    # ------------------------------------------------------------------

    def _build_data_dictionary(self, parent):
        toolbar = ttk.Frame(parent)
        toolbar.pack(fill=tk.X, pady=2)
        refresh_btn = ttk.Button(toolbar, text='\u21bb Refresh',
                                  command=self._refresh_data_dictionary)
        refresh_btn.pack(side=tk.LEFT, padx=4, pady=2)
        add_tooltip(refresh_btn, 'Regenerate data dictionary from current schema')

        copy_btn = ttk.Button(toolbar, text='Copy TSV',
                               command=self._copy_data_dict_tsv)
        copy_btn.pack(side=tk.LEFT, padx=2, pady=2)
        add_tooltip(copy_btn, 'Copy data dictionary to clipboard as TSV')

        tree_frame = ttk.Frame(parent)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        columns = ('table', 'column', 'type', 'pk', 'fk_ref', 'nullable',
                   'default', 'description')
        self._dict_tree = ttk.Treeview(tree_frame, columns=columns,
                                        show='headings', selectmode='browse')
        col_config = {
            'table':       ('Table', 140),
            'column':      ('Column', 180),
            'type':        ('Type', 80),
            'pk':          ('PK', 40),
            'fk_ref':      ('FK Reference', 180),
            'nullable':    ('Nullable', 60),
            'default':     ('Default', 100),
            'description': ('Description', 300),
        }
        for col, (heading, width) in col_config.items():
            self._dict_tree.heading(col, text=heading,
                command=lambda c=col: self._sort_dict(c))
            self._dict_tree.column(col, width=width, minwidth=40)

        dict_ysb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL,
                                   command=self._dict_tree.yview)
        dict_xsb = ttk.Scrollbar(tree_frame, orient=tk.HORIZONTAL,
                                   command=self._dict_tree.xview)
        self._dict_tree.configure(yscrollcommand=dict_ysb.set,
                                   xscrollcommand=dict_xsb.set)
        self._dict_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        dict_ysb.pack(side=tk.RIGHT, fill=tk.Y)
        dict_xsb.pack(side=tk.BOTTOM, fill=tk.X)

        # Alternate row colors
        self._dict_tree.tag_configure('even', background='#f0f0f0')
        self._dict_tree.tag_configure('odd', background='#ffffff')

        self.after(100, self._refresh_data_dictionary)

    def _refresh_data_dictionary(self):
        tree = self._dict_tree
        tree.delete(*tree.get_children())

        # Auto-generated descriptions based on naming conventions
        desc_map = {
            # sprites
            ('sprites', 'name'): 'Unique sprite identifier',
            ('sprites', 'palette'): 'JSON: character → [r,g,b] color mapping',
            ('sprites', 'pixels'): 'JSON: array of row strings using palette characters',
            ('sprites', 'width'): 'Sprite width in pixels',
            ('sprites', 'height'): 'Sprite height in pixels',
            ('sprites', 'action_point_x'): 'X pixel where sprite anchors to tile center',
            ('sprites', 'action_point_y'): 'Y pixel where sprite anchors to tile center',
            ('sprites', 'sprite_set'): 'Organizational group (editor-only)',
            # animations
            ('animations', 'name'): 'Unique animation identifier',
            ('animations', 'target_type'): 'Category: creature, tile, or world_object',
            ('animation_frames', 'frame_index'): 'Playback order (0-based)',
            ('animation_frames', 'duration_ms'): 'How long this frame displays',
            ('animation_bindings', 'target_name'): 'Sprite/species name this binding applies to',
            ('animation_bindings', 'behavior'): 'Creature state (idle, walk_north, etc.)',
            # composites
            ('composite_sprites', 'root_layer'): 'Layer name that serves as the tree root',
            ('composite_layers', 'z_layer'): 'Draw order (higher = on top)',
            ('composite_layers', 'default_sprite'): 'Sprite shown when no variant is active',
            ('layer_connections', 'parent_socket_x'): 'X pixel on parent where child attaches',
            ('layer_connections', 'parent_socket_y'): 'Y pixel on parent where child attaches',
            ('layer_connections', 'child_anchor_x'): 'X pixel on child that aligns to parent socket',
            ('layer_connections', 'child_anchor_y'): 'Y pixel on child that aligns to parent socket',
            ('layer_variants', 'variant_name'): 'Named variant (e.g. happy, closed, angry)',
            ('composite_animations', 'loop'): '1 = repeat continuously, 0 = play once',
            ('composite_animations', 'duration_ms'): 'Total animation length in ms',
            ('composite_animations', 'time_scale'): 'Speed multiplier (0.5=slow, 2.0=fast)',
            ('composite_anim_keyframes', 'time_ms'): 'Keyframe placement in timeline',
            ('composite_anim_keyframes', 'offset_x'): 'Horizontal shift from rest position (px)',
            ('composite_anim_keyframes', 'offset_y'): 'Vertical shift from rest position (px)',
            ('composite_anim_keyframes', 'rotation_deg'): 'Rotation around connection anchor (degrees)',
            ('composite_anim_keyframes', 'variant_name'): 'Sprite variant to show at this keyframe',
            ('composite_anim_keyframes', 'tint_r'): 'Red tint overlay (0-255)',
            ('composite_anim_keyframes', 'tint_g'): 'Green tint overlay (0-255)',
            ('composite_anim_keyframes', 'tint_b'): 'Blue tint overlay (0-255)',
            ('composite_anim_keyframes', 'opacity'): 'Layer opacity (0.0=invisible, 1.0=solid)',
            ('composite_anim_keyframes', 'scale'): 'Layer scale factor (1.0=normal, 0.5=half, 2.0=double)',
            ('composite_anim_bindings', 'flip_h'): 'Mirror animation horizontally',
            # species
            ('species', 'playable'): '1 = player-selectable species',
            ('species', 'tile_scale'): 'Visual size multiplier on the tile grid',
            ('species', 'composite_name'): 'Composite sprite for multi-layer rendering',
            ('species_stats', 'stat'): 'Stat name (strength, agility, etc.)',
            ('species_stats', 'value'): 'Base stat value for this species',
            # items
            ('items', 'class'): 'Item subclass: item, stackable, consumable, ammunition, equippable, weapon, wearable, structure',
            ('items', 'key'): 'Unique item identifier',
            ('items', 'inventoriable'): '1 = can be picked up into inventory',
            ('items', 'buffs'): 'JSON: stat → modifier mapping',
            ('items', 'max_stack_size'): 'Max items per inventory stack (stackable types)',
            ('items', 'quantity'): 'Current stack count',
            ('items', 'duration'): 'Effect duration in seconds (consumables)',
            ('items', 'destroy_on_use_probability'): 'Chance (0-1) ammo is consumed on use',
            ('items', 'slot_count'): 'Number of equipment slots this item occupies',
            ('items', 'durability_max'): 'Maximum durability before breaking',
            ('items', 'durability_current'): 'Current durability remaining',
            ('items', 'render_on_creature'): '1 = visually display on equipped creature',
            ('items', 'damage'): 'Base damage value',
            ('items', 'attack_time_ms'): 'Attack animation/cooldown duration',
            ('items', 'directions'): 'JSON: valid attack direction list',
            ('items', 'range'): 'Attack range in tiles',
            ('items', 'ammunition_type'): 'Required ammo item class',
            ('items', 'collision'): '1 = blocks movement',
            ('items', 'footprint'): 'JSON: list of [x,y] tiles this structure occupies',
            ('items', 'collision_mask'): 'JSON: list of [x,y] tiles that block movement',
            ('items', 'entry_points'): 'JSON: offset → [x,y] spawn point mapping',
            ('items', 'nested_map'): 'Map name to enter when interacting with this structure',
            # tile_templates
            ('tile_templates', 'key'): 'Unique tile template identifier',
            ('tile_templates', 'walkable'): '1 = creatures can walk on this tile',
            ('tile_templates', 'covered'): '1 = acts as roof/ceiling (unused)',
            ('tile_templates', 'animation_name'): 'Animation to play on this tile',
            # tile_sets
            ('tile_sets', 'tile_set'): 'Name of the tile set this entry belongs to',
            ('tile_sets', 'tile_template'): 'Base tile template providing defaults',
            ('tile_sets', 'nested_map'): 'Map entered when stepping on this tile',
            ('tile_sets', 'linked_map'): 'Target map for teleportation',
            ('tile_sets', 'linked_x'): 'Target X coordinate (blank = map entrance)',
            ('tile_sets', 'linked_y'): 'Target Y coordinate (blank = map entrance)',
            ('tile_sets', 'linked_z'): 'Target Z level (blank = 0)',
            ('tile_sets', 'link_auto'): '1 = auto-teleport on step, 0 = requires Enter key',
            ('tile_sets', 'stat_mods'): 'JSON: stat modifier dict applied while on this tile',
            ('tile_templates', 'stat_mods'): 'JSON: default stat modifiers for this tile type',
            ('tile_sets', 'animation_name'): 'Override tile animation for this placement',
            ('tile_sets', 'search_text'): 'Arbitrary text for searching/filtering tiles',
            # maps
            ('maps', 'tile_set'): 'Tile set used to build this map',
            ('maps', 'default_tile_template'): 'Template for unset coordinates',
            ('maps', 'entrance_x'): 'Player spawn X when entering this map',
            ('maps', 'entrance_y'): 'Player spawn Y when entering this map',
        }

        con = get_con()
        try:
            tables = [r['name'] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name != 'sqlite_sequence' ORDER BY name").fetchall()]

            row_idx = 0
            for t in tables:
                cols = con.execute(f'PRAGMA table_info("{t}")').fetchall()
                fks = con.execute(f'PRAGMA foreign_key_list("{t}")').fetchall()
                fk_map = {fk['from']: f"{fk['table']}.{fk['to']}" for fk in fks}

                for c in cols:
                    cname = c['name']
                    pk = 'PK' if c['pk'] else ''
                    fk_ref = fk_map.get(cname, '')
                    nullable = '' if c['notnull'] else 'YES'
                    default = str(c['dflt_value']) if c['dflt_value'] is not None else ''
                    desc = desc_map.get((t, cname), '')
                    tag = 'even' if row_idx % 2 == 0 else 'odd'
                    tree.insert('', tk.END, values=(
                        t, cname, c['type'], pk, fk_ref,
                        nullable, default, desc), tags=(tag,))
                    row_idx += 1
        finally:
            con.close()

    def _sort_dict(self, col):
        items = [(self._dict_tree.set(k, col), k)
                 for k in self._dict_tree.get_children('')]
        items.sort(key=lambda x: x[0])
        for i, (_, k) in enumerate(items):
            self._dict_tree.move(k, '', i)
            tag = 'even' if i % 2 == 0 else 'odd'
            self._dict_tree.item(k, tags=(tag,))
        self._dict_tree.heading(
            col, command=lambda: self._sort_dict_desc(col))

    def _sort_dict_desc(self, col):
        items = [(self._dict_tree.set(k, col), k)
                 for k in self._dict_tree.get_children('')]
        items.sort(key=lambda x: x[0], reverse=True)
        for i, (_, k) in enumerate(items):
            self._dict_tree.move(k, '', i)
            tag = 'even' if i % 2 == 0 else 'odd'
            self._dict_tree.item(k, tags=(tag,))
        self._dict_tree.heading(
            col, command=lambda: self._sort_dict(col))

    def _copy_data_dict_tsv(self):
        columns = self._dict_tree['columns']
        if not columns:
            return
        lines = ['\t'.join(columns)]
        for item in self._dict_tree.get_children(''):
            values = [self._dict_tree.set(item, c) for c in columns]
            lines.append('\t'.join(values))
        tsv = '\n'.join(lines)
        self.clipboard_clear()
        self.clipboard_append(tsv)
        self._status_var.set(f'Copied {len(lines)-1} rows to clipboard')

    # ------------------------------------------------------------------
    # Cheat Sheet sub-tab
    # ------------------------------------------------------------------

    def _build_cheatsheet(self, parent):
        mono = tkfont.Font(family='Courier', size=10)

        text = tk.Text(parent, font=mono, wrap=tk.WORD,
                       bg='#1e1e1e', fg='#d4d4d4',
                       padx=12, pady=8, state=tk.NORMAL)
        sb = ttk.Scrollbar(parent, orient=tk.VERTICAL, command=text.yview)
        text.configure(yscrollcommand=sb.set)
        sb.pack(side=tk.RIGHT, fill=tk.Y)
        text.pack(fill=tk.BOTH, expand=True, padx=4, pady=4)

        # Configure tags for syntax highlighting
        heading_font = tkfont.Font(family='Courier', size=11, weight='bold')
        text.tag_configure('heading', foreground='#569cd6', font=heading_font)
        text.tag_configure('subheading', foreground='#4ec9b0', font=heading_font)
        text.tag_configure('keyword', foreground='#c586c0')
        text.tag_configure('divider', foreground='#555')
        text.tag_configure('comment', foreground='#6a9955')
        text.tag_configure('pipe', foreground='#555')

        # Insert with basic formatting
        for line in CHEATSHEET.strip().split('\n'):
            stripped = line.strip()
            if stripped.startswith('# ') and not stripped.startswith('##'):
                text.insert(tk.END, line + '\n', 'heading')
            elif stripped.startswith('## '):
                text.insert(tk.END, line + '\n', 'subheading')
            elif stripped.startswith('──') or stripped.startswith('───'):
                text.insert(tk.END, line + '\n', 'divider')
            elif stripped.startswith('--'):
                text.insert(tk.END, line + '\n', 'comment')
            else:
                text.insert(tk.END, line + '\n')

        text.configure(state=tk.DISABLED)

    # ------------------------------------------------------------------
    # Schema browser
    # ------------------------------------------------------------------

    def _refresh_schema(self):
        tree = self._schema_tree
        tree.delete(*tree.get_children())

        con = get_con()
        try:
            tables = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "ORDER BY name"
            ).fetchall()
            for t in tables:
                tname = t['name']
                node = tree.insert('', tk.END, text=tname, open=False,
                                    tags=('table',))
                # Add columns as children
                cols = con.execute(
                    f'PRAGMA table_info("{tname}")').fetchall()
                for c in cols:
                    pk_marker = ' [PK]' if c['pk'] else ''
                    notnull = ' NOT NULL' if c['notnull'] else ''
                    default = f' = {c["dflt_value"]}' if c['dflt_value'] is not None else ''
                    label = f"{c['name']}  ({c['type']}{pk_marker}{notnull}{default})"
                    tree.insert(node, tk.END, text=label,
                                tags=('column', tname, c['name']))
        finally:
            con.close()

    def _on_schema_double_click(self, event):
        """Insert table or column name into the query editor."""
        item = self._schema_tree.focus()
        if not item:
            return
        tags = self._schema_tree.item(item, 'tags')
        if 'table' in tags:
            name = self._schema_tree.item(item, 'text')
            self._query_text.insert(tk.INSERT, name)
        elif 'column' in tags:
            # tags = ('column', table_name, column_name)
            if len(tags) >= 3:
                self._query_text.insert(tk.INSERT, f'{tags[1]}.{tags[2]}')

    # ------------------------------------------------------------------
    # Query execution
    # ------------------------------------------------------------------

    def _run_query(self):
        # Get selected text or full text
        try:
            sql = self._query_text.get(tk.SEL_FIRST, tk.SEL_LAST).strip()
        except tk.TclError:
            sql = self._query_text.get('1.0', tk.END).strip()

        if not sql:
            return

        # Hide previous error
        self._error_text.pack_forget()

        # Clear results
        self._results_tree.delete(*self._results_tree.get_children())
        self._results_tree['columns'] = ()
        self._rows_var.set('')

        con = get_con()
        try:
            t0 = time.time()
            cursor = con.execute(sql)
            elapsed = time.time() - t0

            if cursor.description:
                # SELECT-like query with results
                columns = [d[0] for d in cursor.description]
                rows = cursor.fetchall()
                con.commit()  # commit in case of side effects

                # Configure columns
                self._results_tree['columns'] = columns
                for col in columns:
                    self._results_tree.heading(col, text=col,
                        command=lambda c=col: self._sort_results(c))
                    self._results_tree.column(col, width=100, minwidth=50)

                # Insert rows
                for row in rows:
                    values = [str(v) if v is not None else 'NULL' for v in row]
                    self._results_tree.insert('', tk.END, values=values)

                self._rows_var.set(
                    f'{len(rows)} row{"s" if len(rows) != 1 else ""} '
                    f'in {elapsed*1000:.1f}ms')
                self._status_var.set(f'Query OK — {len(rows)} rows')
            else:
                # Non-SELECT (INSERT, UPDATE, DELETE, etc.)
                affected = cursor.rowcount
                con.commit()
                elapsed = time.time() - t0
                self._status_var.set(
                    f'OK — {affected} row{"s" if affected != 1 else ""} '
                    f'affected in {elapsed*1000:.1f}ms')
                self._rows_var.set('')
                # Refresh schema in case DDL changed structure
                self._refresh_schema()

        except sqlite3.Error as e:
            con.rollback()
            self._status_var.set('Error')
            self._error_text.configure(state=tk.NORMAL)
            self._error_text.delete('1.0', tk.END)
            self._error_text.insert('1.0', f'ERROR: {e}')
            self._error_text.configure(state=tk.DISABLED)
            self._error_text.pack(fill=tk.X, padx=4, pady=(0, 4))
        finally:
            con.close()

    def _sort_results(self, col):
        """Sort results treeview by clicking column header."""
        items = [(self._results_tree.set(k, col), k)
                 for k in self._results_tree.get_children('')]
        # Try numeric sort, fall back to string
        try:
            items.sort(key=lambda x: float(x[0]) if x[0] != 'NULL' else float('-inf'))
        except ValueError:
            items.sort(key=lambda x: x[0])

        for i, (_, k) in enumerate(items):
            self._results_tree.move(k, '', i)

        # Toggle sort direction on next click
        self._results_tree.heading(
            col, command=lambda: self._sort_results_desc(col))

    def _sort_results_desc(self, col):
        items = [(self._results_tree.set(k, col), k)
                 for k in self._results_tree.get_children('')]
        try:
            items.sort(key=lambda x: float(x[0]) if x[0] != 'NULL' else float('-inf'),
                       reverse=True)
        except ValueError:
            items.sort(key=lambda x: x[0], reverse=True)

        for i, (_, k) in enumerate(items):
            self._results_tree.move(k, '', i)

        self._results_tree.heading(
            col, command=lambda: self._sort_results(col))

    def _clear_query(self):
        self._query_text.delete('1.0', tk.END)
        self._error_text.pack_forget()

    def _copy_results_tsv(self):
        """Copy results to clipboard as TSV."""
        columns = self._results_tree['columns']
        if not columns:
            return
        lines = ['\t'.join(columns)]
        for item in self._results_tree.get_children(''):
            values = [self._results_tree.set(item, c) for c in columns]
            lines.append('\t'.join(values))
        tsv = '\n'.join(lines)
        self.clipboard_clear()
        self.clipboard_append(tsv)
        self._status_var.set(f'Copied {len(lines)-1} rows to clipboard')
