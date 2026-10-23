"""Small Tkinter window: paste URLs, click Connect."""
from __future__ import annotations

import logging
import os
import queue
import threading
import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk

from . import APP_NAME, __version__, platform, settings, urls
from .logging_setup import MaskFilter, log_dir, log_file, setup_logging
from .engine import friendly_error, probe
from .platform import plays_out_loud
from .session import Options, Session
from .welcome import should_show

DOT = {"idle": "#9aa0a6", "connecting": "#f9ab00", "retrying": "#f9ab00", "live": "#1e8e3e",
       "error": "#d93025", "stopped": "#9aa0a6"}
RECOMMENDED_SUFFIX = " (recommended)"


class _QueueLog(logging.Handler):
    def __init__(self, q: queue.Queue):
        super().__init__()
        self.q = q
        self.addFilter(MaskFilter())

    def emit(self, record: logging.LogRecord) -> None:
        self.q.put(("log", urls.mask(self.format(record))))


class App:
    def __init__(self, root: tk.Tk):
        self.root, self.plat = root, platform.current()
        self.session: Session | None = None
        self.q: queue.Queue = queue.Queue()
        self.cfg = settings.load()
        lg = logging.getLogger("streambridge")
        for old in [x for x in lg.handlers if isinstance(x, _QueueLog)]:   # after a reset/reload
            lg.removeHandler(old)
        h = _QueueLog(self.q)
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s", "%H:%M:%S"))
        lg.addHandler(h)
        self.log = logging.getLogger("streambridge")

        root.title(f"{APP_NAME} {__version__}")
        menubar = tk.Menu(root)
        helpm = tk.Menu(menubar, tearoff=0)
        helpm.add_command(label="Welcome / Setup check…", command=self.show_welcome)
        helpm.add_command(label="About", command=self.about)
        menubar.add_cascade(label="Help", menu=helpm)
        root.config(menu=menubar)
        root.minsize(560, 0)
        f = ttk.Frame(root, padding=16)
        f.grid(sticky="nsew")
        root.columnconfigure(0, weight=1)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, text="Use your phone as this computer's camera and microphone",
                  font=("", 12, "bold")).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))

        # --- URLs (recent lists, Same phone) ---
        c = self.cfg
        ttk.Label(f, text="Video URL").grid(row=1, column=0, sticky="w", padx=(0, 8))
        self.video = ttk.Combobox(f, values=c["recent_video"], width=46)
        self.video.set(c["video_url"]); self.video.grid(row=1, column=1, columnspan=2, sticky="ew", pady=2)
        ttk.Label(f, text="Audio URL").grid(row=2, column=0, sticky="w", padx=(0, 8))
        self.audio = ttk.Combobox(f, values=c["recent_audio"], width=38)
        self.audio.set(c["audio_url"]); self.audio.grid(row=2, column=1, sticky="ew", pady=2)
        ttk.Button(f, text="Same phone", command=self.fill_audio).grid(row=2, column=2, padx=(6, 0))
        ttk.Label(f, text="Fill one or both, e.g. 192.168.1.5:8080/video and https://10.0.2.16:4747/audio.wav",
                  foreground="#5f6368").grid(row=3, column=1, columnspan=2, sticky="w")

        # --- Login ---
        login = ttk.LabelFrame(f, text="Login (optional)", padding=8)
        login.grid(row=4, column=0, columnspan=3, sticky="ew", pady=8)
        login.columnconfigure(1, weight=1); login.columnconfigure(3, weight=1)
        self.v_user = tk.StringVar(value=c["username"])
        self.v_pass = tk.StringVar(value=c["password"])
        self.v_show = tk.BooleanVar(value=False)
        self.v_remember = tk.BooleanVar(value=c["remember_password"])
        ttk.Label(login, text="User").grid(row=0, column=0, padx=(0, 6))
        ttk.Entry(login, textvariable=self.v_user, width=14).grid(row=0, column=1, sticky="ew")
        ttk.Label(login, text="Password").grid(row=0, column=2, padx=6)
        self.pw = ttk.Entry(login, textvariable=self.v_pass, show="•", width=14)
        self.pw.grid(row=0, column=3, sticky="ew")
        ttk.Checkbutton(login, text="show", variable=self.v_show,
                        command=lambda: self.pw.config(show="" if self.v_show.get() else "•")).grid(row=0, column=4, padx=4)
        kr = settings.keyring_available()
        cb = ttk.Checkbutton(login, text="Remember password (system keychain)" if kr else
                             "Remember password (needs the 'keyring' package)", variable=self.v_remember)
        cb.grid(row=1, column=0, columnspan=5, sticky="w", pady=(6, 0))
        if not kr:
            cb.state(["disabled"]); self.v_remember.set(False)

        # --- Options ---
        opt = ttk.Frame(f); opt.grid(row=5, column=0, columnspan=3, sticky="ew")
        ttk.Label(opt, text="Camera size").grid(row=0, column=0, sticky="w")
        self.size = ttk.Combobox(opt, values=settings.SIZE_CHOICES, width=20)
        saved = c["size"] if c["size"] in settings.SIZE_CHOICES else settings.SIZE_CHOICES[0]
        self.size.set(saved); self.size.grid(row=0, column=1, sticky="w", padx=6)
        self.v_strict = tk.BooleanVar(value=c["strict_tls"])
        ttk.Checkbutton(opt, text="Strict HTTPS (also verify certificates on the local network)",
                        variable=self.v_strict).grid(row=1, column=0, columnspan=3, sticky="w", pady=(4, 0))
        self.output = None
        if self.plat.shows_output_choice or os.environ.get("STREAMBRIDGE_SHOW_AUDIO_OUTPUT"):
            ttk.Label(opt, text=f"Audio output ({self.plat.name})").grid(row=2, column=0, sticky="w", pady=(4, 0))
            self.output = ttk.Combobox(opt, state="readonly", width=34)
            self.output.grid(row=2, column=1, sticky="w", padx=6, pady=(4, 0))
            ttk.Button(opt, text="Refresh", command=self.refresh_outputs).grid(row=2, column=2, sticky="w", pady=(4, 0))
            self.output_hint = ttk.Label(opt, text="", wraplength=500, foreground="#5f6368")
            self.output_hint.grid(row=3, column=0, columnspan=3, sticky="w")
        ttk.Label(opt, text="Mic delay").grid(row=5, column=0, sticky="w", pady=(4, 0))
        self.delay = ttk.Combobox(opt, state="readonly", width=20,
                                  values=["Low (~30 ms)", "Normal (~60 ms)", "Stable (~150 ms)"])
        self.delay.set({"low": "Low (~30 ms)", "normal": "Normal (~60 ms)", "stable": "Stable (~150 ms)"}.get(c.get("audio_latency"), "Low (~30 ms)"))
        self.delay.grid(row=5, column=1, sticky="w", padx=6, pady=(4, 0))
        ttk.Label(opt, text="Use Stable if the mic crackles on weak Wi-Fi", foreground="#5f6368").grid(
            row=5, column=2, sticky="w", pady=(4, 0))
        self.v_auto = tk.BooleanVar(value=c["autoconnect"])
        ttk.Checkbutton(opt, text="Connect automatically when StreamBridge opens",
                        variable=self.v_auto).grid(row=6, column=0, columnspan=3, sticky="w", pady=(4, 0))

        # --- Buttons ---
        btns = ttk.Frame(f); btns.grid(row=6, column=0, columnspan=3, sticky="ew", pady=10)
        ttk.Button(btns, text="About", command=self.about).pack(side="left")
        ttk.Button(btns, text="Reset to defaults…", command=self.on_reset).pack(side="left", padx=4)
        self.b_conn = ttk.Button(btns, text="Connect", command=self.on_connect)
        self.b_conn.pack(side="right")
        self.b_test = ttk.Button(btns, text="Test URLs", command=self.on_test)
        self.b_test.pack(side="right", padx=4)

        # --- Status ---
        self.status = {}
        r = 7
        for kind, title, name in (("camera", "Camera", self.plat.camera_name), ("mic", "Microphone", self.plat.mic_name)):
            card = ttk.Frame(f, padding=(0, 3)); card.grid(row=r, column=0, columnspan=3, sticky="ew"); r += 1
            dot = tk.Canvas(card, width=12, height=12, highlightthickness=0)
            dot.create_oval(2, 2, 11, 11, fill=DOT["idle"], outline="", tags="d")
            dot.pack(side="left", padx=(0, 6))
            ttk.Label(card, text=title, font=("", 10, "bold"), width=11).pack(side="left")
            lbl = ttk.Label(card, text=f"Off. Apps will see “{name}”", wraplength=420)
            lbl.pack(side="left", fill="x")
            self.status[kind] = (dot, lbl, name)
        self.msg = ttk.Label(f, text="", foreground="#3c4043", wraplength=520)
        self.msg.grid(row=r, column=0, columnspan=3, sticky="w"); r += 1
        self.deps = ttk.Frame(f); self.deps.grid(row=r, column=0, columnspan=3, sticky="ew"); r += 1

        # --- Details log ---
        self.v_details = tk.BooleanVar(value=False)
        drow = ttk.Frame(f); drow.grid(row=r, column=0, columnspan=3, sticky="ew", pady=(8, 0)); r += 1
        ttk.Checkbutton(drow, text="Show details", variable=self.v_details,
                        command=self.toggle_details).pack(side="left")
        ttk.Button(drow, text="Copy log", command=self.copy_log).pack(side="right")
        ttk.Button(drow, text="Open log folder", command=self.open_log_folder).pack(side="right", padx=4)
        self.logbox = tk.Text(f, height=8, width=70, state="disabled", font=("TkFixedFont", 9))
        self.log_row = r

        self.refresh_deps()
        if self.output is not None:
            self.refresh_outputs()
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        root.after(100, self.poll)
        if c["autoconnect"] and (c["video_url"] or c["audio_url"]):
            root.after(500, self.on_connect)
        if should_show(c):
            root.after(300, self.show_welcome)

    # ---- welcome / setup check (first run; Help menu) -----------------------
    def show_welcome(self) -> None:
        from .welcome.dialog import WelcomeDialog
        WelcomeDialog(self.root, self.plat, self.cfg.get("welcome_dont_show", False), self.set_welcome_dont_show)

    def set_welcome_dont_show(self, value: bool) -> None:
        self.cfg["welcome_dont_show"] = bool(value)
        on_disk = settings.load()
        on_disk["welcome_dont_show"] = bool(value)
        settings.save(on_disk)

    # ---- requirements panel -------------------------------------------------
    def refresh_deps(self) -> None:
        for w in self.deps.winfo_children():
            w.destroy()
        missing = [d for d in self.plat.check() if not d.ok]
        if not missing:
            return
        box = ttk.LabelFrame(self.deps, text="One-time setup needed (StreamBridge never installs anything itself)",
                             padding=8)
        box.pack(fill="x", pady=(8, 0))
        for d in missing:
            ttk.Label(box, text=f"• {d.name} (for the {d.needed_for})", font=("", 10, "bold")).pack(anchor="w")
            ttk.Label(box, text=d.detail + ". " + " ".join(s for s in d.steps if not s.startswith("  ")),
                      wraplength=500, foreground="#3c4043").pack(anchor="w", padx=12)
            row = ttk.Frame(box); row.pack(anchor="w", padx=12, pady=(2, 6))
            ttk.Button(row, text="Open official page", command=lambda u=d.url: webbrowser.open(u)).pack(side="left")
            cmds = [s.strip() for s in d.steps if s.startswith("  ")]
            if cmds:
                ttk.Button(row, text="Copy commands", command=lambda s=cmds: self.copy("\n".join(s))).pack(
                    side="left", padx=6)
        ttk.Button(box, text="Check again", command=self.refresh_deps).pack(anchor="e")

    def copy(self, text: str) -> None:
        self.root.clipboard_clear(); self.root.clipboard_append(text)
        self.msg.config(text="Copied. Paste into a terminal and run the line for your distribution yourself.")

    # ---- audio output (Windows/macOS) ---------------------------------------
    def refresh_outputs(self) -> None:
        rec = self.plat.recommended_output or ""
        names = self.plat.audio_outputs()
        found = [n for n in names if rec and n.lower().startswith(rec.lower())]
        values = [rec + RECOMMENDED_SUFFIX] + [n for n in names if n not in found]
        self.output.config(values=values)
        saved = self.cfg.get("audio_output", "auto")
        self.output.set(saved if saved in values else values[0])
        if found:
            self.output_hint.config(text=f"Apps choose “{self.plat.mic_name}” as the microphone.", foreground="#5f6368")
        else:
            self.output_hint.config(text=f"“{rec}” was not found. Install it (see setup below), then click Refresh.",
                                    foreground="#b45309")

    def delay_value(self) -> str:
        return self.delay.get().split()[0].lower() if self.delay.get() else "low"

    def output_value(self) -> str:
        if self.output is None:
            return "auto"
        v = self.output.get()
        return "auto" if not v or v.endswith(RECOMMENDED_SUFFIX) else v

    def confirm_output(self) -> bool:
        v = self.output_value()
        if self.audio.get().strip() and plays_out_loud(v):
            return messagebox.askyesno(APP_NAME, f"“{v}” looks like real speakers or headphones, so the phone "
                                       "audio would play out loud there and would NOT become a microphone.\n\n"
                                       "Use it anyway?")
        return True

    # ---- actions ------------------------------------------------------------
    def fill_audio(self) -> None:
        g = urls.guess_audio_url(self.video.get())
        if g:
            self.audio.set(g)

    def collect(self) -> Options | None:
        """Validate fields, move login-in-URL into the fields, remember settings."""
        video, audio = urls.normalize(self.video.get()), urls.normalize(self.audio.get())
        if not video and not audio:
            messagebox.showwarning(APP_NAME, "Enter the phone's video URL, audio URL, or both."); return None
        user, pwd = self.v_user.get().strip(), self.v_pass.get()
        clean = {}
        for label, u in (("Video", video), ("Audio", audio)):
            if not u:
                clean[label] = ""; continue
            c, uu, up = urls.split_credentials(u)
            if uu and not user:
                user, pwd = uu, up
            try:
                urls.parse(c)
            except urls.UrlError as e:
                messagebox.showwarning(APP_NAME, f"{label} URL: {e}.\n\nExample: http://192.168.1.5:8080/video")
                return None
            clean[label] = c
        self.video.set(clean["Video"]); self.audio.set(clean["Audio"])
        self.v_user.set(user); self.v_pass.set(pwd)
        try:
            size = settings.parse_size(self.size.get())
        except ValueError as e:
            messagebox.showwarning(APP_NAME, str(e)); return None
        self.cfg.update(video_url=clean["Video"], audio_url=clean["Audio"], username=user, password=pwd,
                        size=self.size.get(), strict_tls=self.v_strict.get(), remember_password=self.v_remember.get(),
                        autoconnect=self.v_auto.get(), audio_latency=self.delay_value(), audio_output=self.output.get() if self.output else "auto",
                        recent_video=urls.add_recent(self.cfg["recent_video"], clean["Video"]),
                        recent_audio=urls.add_recent(self.cfg["recent_audio"], clean["Audio"]))
        try:
            settings.save(self.cfg)
        except OSError as e:
            self.log.warning("Could not save settings: %s", e)
        self.video.config(values=self.cfg["recent_video"]); self.audio.config(values=self.cfg["recent_audio"])
        return Options(clean["Video"], clean["Audio"], user, pwd, size, 30.0, self.v_strict.get(),
                       audio_output=self.output_value(), audio_latency=self.delay_value())

    def on_test(self) -> None:
        o = self.collect()
        if not o:
            return
        self.msg.config(text="Testing (no camera or mic is created)…")
        self.b_test.state(["disabled"])

        def work():
            out = []
            for kind, raw in (("video", o.video_url), ("audio", o.audio_url)):
                if raw:
                    try:
                        out.append(f"{kind.title()}: " + probe(urls.parse(raw, o.username, o.password), kind, o.strict_tls))
                    except Exception as e:  # network/decoder errors: shown in the window
                        self.log.warning("test %s: %s", kind, urls.mask(f'{type(e).__name__}: {e}'))
                        out.append(f"{kind.title()}: {friendly_error(e)}")
            for line in out:
                self.log.info("Test %s", line)
            self.q.put(("msg", "\n".join(out))); self.q.put(("test_done", None))
        threading.Thread(target=work, daemon=True).start()

    def on_connect(self) -> None:
        if self.session:
            self.disconnect(); return
        o = self.collect()
        if not o or not self.confirm_output():
            return
        try:
            self.session = Session(o, self.plat, lambda s: self.q.put(("status", s)))
            self.session.start()
        except Exception as e:  # shown in the window; also logged so 'Copy log' has it
            self.log.warning("connect failed: %s", urls.mask(f'{type(e).__name__}: {e}'))
            if self.session:
                self.session.stop()
            self.session = None
            self.msg.config(text=str(e) if isinstance(e, (urls.UrlError, RuntimeError)) else friendly_error(e))
            return
        self.log.info("Connected: %r", o)
        self.b_conn.config(text="Disconnect"); self.b_test.state(["disabled"])
        self.msg.config(text="")

    def disconnect(self) -> None:
        s, self.session = self.session, None
        if s:
            t = time.monotonic(); s.stop()
            self.log.info("Disconnected in %.2fs", time.monotonic() - t)
        self.b_conn.config(text="Connect"); self.b_test.state(["!disabled"])
        for kind, (_, _, name) in self.status.items():
            self.set_status(kind, "idle", f"Off. Apps will see “{name}”")

    def set_status(self, kind: str, state: str, text: str) -> None:
        dot, lbl, _ = self.status[kind]
        dot.itemconfig("d", fill=DOT.get(state, "#9aa0a6"))
        lbl.config(text=text)

    def toggle_details(self) -> None:
        if self.v_details.get():
            self.logbox.grid(row=self.log_row, column=0, columnspan=3, sticky="nsew", pady=(4, 0))
        else:
            self.logbox.grid_remove()

    def append_log(self, line: str) -> None:
        self.logbox.config(state="normal"); self.logbox.insert("end", line + "\n")
        if int(self.logbox.index("end").split(".")[0]) > 500:
            self.logbox.delete("1.0", "100.0")
        self.logbox.see("end"); self.logbox.config(state="disabled")

    def open_log_folder(self) -> None:
        import subprocess, sys
        d = log_dir()
        os.makedirs(d, exist_ok=True)
        if sys.platform.startswith("win"):
            os.startfile(d)  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", d])

    def copy_log(self) -> None:
        try:
            with open(log_file(), encoding="utf-8", errors="replace") as fh:
                text = urls.mask(fh.read()[-60000:])
        except OSError as e:
            self.msg.config(text=f"No log yet ({e.strerror})."); return
        self.copy(text)
        self.msg.config(text=f"Log copied ({log_file()}). Passwords are masked.")

    def on_reset(self) -> None:
        dlg = tk.Toplevel(self.root); dlg.title("Reset to defaults"); dlg.transient(self.root); dlg.grab_set()
        fr = ttk.Frame(dlg, padding=14); fr.pack(fill="both")
        logs = tk.BooleanVar(value=False)
        ttk.Label(fr, text="This removes only StreamBridge's own data:", font=("", 10, "bold")).pack(anchor="w")
        lst = ttk.Label(fr, justify="left", wraplength=520); lst.pack(anchor="w", pady=6)

        def refresh():
            lst.config(text="\n".join("• " + i for i in settings.reset_plan(logs.get())))
        ttk.Checkbutton(fr, text="Also delete the log files", variable=logs, command=refresh).pack(anchor="w")
        ttk.Label(fr, text="Nothing else on this computer is touched. Disconnects first.",
                  foreground="#5f6368").pack(anchor="w", pady=(6, 0))
        refresh()
        res = {"ok": False}
        row = ttk.Frame(fr); row.pack(anchor="e", pady=(10, 0))
        ttk.Button(row, text="Cancel", command=dlg.destroy).pack(side="right")
        ttk.Button(row, text="Reset", command=lambda: (res.update(ok=True), dlg.destroy())).pack(side="right", padx=6)
        self.root.wait_window(dlg)
        if res["ok"]:
            self.do_reset(logs.get())

    def do_reset(self, include_logs: bool) -> "App":
        self.disconnect()
        removed = settings.reset(include_logs)
        if include_logs:
            setup_logging()            # start a fresh log file
        self.log.info("Reset to defaults: removed %d item(s)", len(removed))
        root = self.root
        for w in root.winfo_children():
            w.destroy()
        new = App(root)                # reload defaults (Mic delay Low, ...) without restarting
        new.msg.config(text="Reset to defaults done.")
        return new

    def about(self) -> None:
        messagebox.showinfo(APP_NAME, f"{APP_NAME} {__version__}\n\nUse your phone (EZ-Cam) as this computer's "
                            f"camera and microphone.\n\nCamera: “{self.plat.camera_name}”\n"
                            f"Microphone: “{self.plat.mic_name}”\n\nPython {'.'.join(map(str, __import__('sys').version_info[:3]))}"
                            f" on {self.plat.name}. MIT License.")

    def poll(self) -> None:
        try:
            while True:
                kind, val = self.q.get_nowait()
                if kind == "msg":
                    self.msg.config(text=val)
                elif kind == "log":
                    self.append_log(val)
                elif kind == "test_done":
                    if not self.session:
                        self.b_test.state(["!disabled"])
                elif kind == "status" and self.session:
                    s = val
                    if s.state == "live":
                        txt = f"Live: {s.source}" + (f", {s.fps:g} fps" if s.fps else "") + f"  →  {s.output}"
                        if s.warning:
                            self.set_status(s.kind, "retrying", f"⚠ {s.warning}. {txt}")   # yellow dot
                            continue
                    elif s.state == "stopped":
                        continue
                    else:
                        txt = s.detail or s.state.title()
                        self.log.info("%s: %s", s.kind, txt)
                    self.set_status(s.kind, s.state, txt)
        except queue.Empty:
            pass
        self.root.after(150, self.poll)

    def on_close(self) -> None:
        self.disconnect()
        self.root.destroy()


def run_gui() -> int:
    setup_logging()
    root = tk.Tk()
    App(root)
    root.mainloop()
    return 0
