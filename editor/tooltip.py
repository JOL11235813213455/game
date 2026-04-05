"""Reusable tooltip for tkinter widgets."""
import tkinter as tk


class Tooltip:
    """Hover tooltip that appears after a short delay."""

    DELAY_MS = 400

    def __init__(self, widget: tk.Widget, text: str):
        self.widget = widget
        self.text = text
        self._tipwindow: tk.Toplevel | None = None
        self._after_id: str | None = None
        widget.bind('<Enter>', self._schedule, add='+')
        widget.bind('<Leave>', self._hide, add='+')
        widget.bind('<ButtonPress>', self._hide, add='+')

    def _schedule(self, event=None):
        self._hide()
        self._after_id = self.widget.after(self.DELAY_MS, self._show)

    def _show(self):
        if self._tipwindow:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry(f'+{x}+{y}')
        label = tk.Label(
            tw, text=self.text, justify=tk.LEFT,
            background='#ffffe0', relief=tk.SOLID, borderwidth=1,
            font=('TkDefaultFont', 9), padx=6, pady=4,
        )
        label.pack()
        self._tipwindow = tw

    def _hide(self, event=None):
        if self._after_id:
            self.widget.after_cancel(self._after_id)
            self._after_id = None
        if self._tipwindow:
            self._tipwindow.destroy()
            self._tipwindow = None


def add_tooltip(widget: tk.Widget, text: str) -> Tooltip:
    """Attach a tooltip to a widget. Returns the Tooltip instance."""
    return Tooltip(widget, text)
