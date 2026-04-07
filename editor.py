#!/usr/bin/env python3
"""
Standalone tkinter editor for the pygame RPG game's SQLite database.
Run from the game directory:  python editor.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'src'))

from editor import EditorApp

if __name__ == '__main__':
    app = EditorApp()
    app.mainloop()