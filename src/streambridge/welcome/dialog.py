"""Tk dialog for the Welcome / Setup check. Shows, never installs."""
from __future__ import annotations

import tkinter as tk
import webbrowser
from tkinter import ttk

from . import build

GREEN, RED = "#1e8e3e", "#d93025"


class WelcomeDialog:
    def __init__(self, parent: tk.Misc, plat, dont_show: bool, on_dont_show, title="Welcome to StreamBridge"):
        self.plat, self.on_dont_show = plat, on_dont_show
        self.win = tk.Toplevel(parent)
        self.win.title(title)
        self.win.transient(parent)
        self.win.resizable(False, False)
        outer = ttk.Frame(self.win, padding=16); outer.pack(fill="both", expand=True)
        ttk.Label(outer, text="Welcome to StreamBridge", font=("", 13, "bold")).pack(anchor="w")
        self.intro = ttk.Label(outer, wraplength=560, justify="left"); self.intro.pack(anchor="w", pady=(6, 10))
        ttk.Label(outer, text=f"Setup check for {plat.name}", font=("", 11, "bold")).pack(anchor="w")
        self.body = ttk.Frame(outer); self.body.pack(fill="x", pady=(4, 8))
        self.summary = ttk.Label(outer, font=("", 10, "bold")); self.summary.pack(anchor="w")
        bottom = ttk.Frame(outer); bottom.pack(fill="x", pady=(10, 0))
        self.v_dont = tk.BooleanVar(value=dont_show)
        ttk.Checkbutton(bottom, text="Don't show this again at start (Help menu reopens it)",
                        variable=self.v_dont, command=lambda: self.on_dont_show(self.v_dont.get())).pack(side="left")
        ttk.Button(bottom, text="Close", command=self.win.destroy).pack(side="right")
        ttk.Button(bottom, text="Re-check", command=self.refresh).pack(side="right", padx=6)
        self.refresh()

    def refresh(self) -> None:
        rep = build(self.plat)
        self.intro.config(text=rep.intro)
        for w in self.body.winfo_children():
            w.destroy()
        for it in rep.items:
            box = ttk.Frame(self.body, padding=(0, 6)); box.pack(fill="x")
            head = ttk.Frame(box); head.pack(fill="x")
            tk.Label(head, text="●", fg=GREEN if it.ok else RED, font=("", 12)).pack(side="left")
            ttk.Label(head, text=f"{it.title}  (for the {it.needed_for})", font=("", 10, "bold")).pack(
                side="left", padx=4)
            ttk.Label(head, text="OK" if it.ok else "Missing", foreground=GREEN if it.ok else RED).pack(side="right")
            ttk.Label(box, text=it.status, foreground="#5f6368", wraplength=540).pack(anchor="w", padx=22)
            if it.ok:
                continue
            for line in it.howto:
                ttk.Label(box, text="• " + line, wraplength=520, justify="left").pack(anchor="w", padx=22)
            if it.copy:
                cmd = ttk.Entry(box, width=74, font=("TkFixedFont", 9))
                cmd.insert(0, it.copy); cmd.configure(state="readonly"); cmd.pack(anchor="w", padx=22, pady=2)
            row = ttk.Frame(box); row.pack(anchor="w", padx=22, pady=(2, 0))
            ttk.Button(row, text="Open official page", command=lambda u=it.url: webbrowser.open(u)).pack(side="left")
            if it.copy:
                ttk.Button(row, text="Copy command", command=lambda c=it.copy: self._copy(c)).pack(side="left", padx=6)
        if rep.all_ok:
            self.summary.config(text="All set. Close this window and paste your phone's URLs.", foreground=GREEN)
        else:
            self.summary.config(text="Install what's missing (or skip what you don't need), then click Re-check.",
                                foreground=RED)

    def _copy(self, text: str) -> None:
        self.win.clipboard_clear(); self.win.clipboard_append(text)
        self.summary.config(text="Copied. Paste it into a terminal and run it yourself.", foreground="#3c4043")
