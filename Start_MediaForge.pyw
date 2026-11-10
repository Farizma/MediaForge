#!/usr/bin/env python3
"""Start_MediaForge.pyw - double-click this to run MediaForge.

It checks that everything the program needs is present, and if something is
missing it ASKS you first and then installs it:

    * a private Python environment (.venv) with PySide6 and yt-dlp   (pip)
    * ffmpeg + ffprobe                                               (Windows: downloaded for you)

Then it starts the program. Run again any time; if nothing is missing it just launches.

Options (for a terminal):  --check   only report what's missing
                           --yes     don't ask, just install
                           --console use the terminal instead of pop-up windows
                           --no-launch   set everything up but don't start the app
Uses only the Python standard library, so it works on a machine with nothing installed.
"""
from __future__ import annotations

import argparse
import os
import queue
import subprocess
import sys
import threading
import time
import traceback
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
MIN_PY = (3, 10)
IS_WIN = sys.platform == "win32"
NO_WINDOW = 0x08000000 if IS_WIN else 0           # CREATE_NO_WINDOW
APP = "MediaForge"


# ------------------------------------------------------------------ paths & checks
def venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if IS_WIN else "bin/python")


def missing_packages(data_dir: Path, updater) -> list[str]:
    """Python packages absent from the private environment (the whole env if it doesn't exist)."""
    py = venv_python()
    if not py.exists():
        return ["PySide6", "yt-dlp"]
    code = ("import importlib.util as u; print(','.join(n for n, m in (('PySide6', 'PySide6'), "
            "('yt-dlp', 'yt_dlp')) if not u.find_spec(m)))")
    try:
        out = subprocess.run([str(py), "-c", code], capture_output=True, text=True, timeout=60,
                             creationflags=NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ["PySide6", "yt-dlp"]
    missing = [x for x in out.split(",") if x]
    if "yt-dlp" in missing and updater.latest_managed_ytdlp(data_dir):
        missing.remove("yt-dlp")            # a downloaded yt-dlp update stands in for the pip one
    return missing


def what_is_missing(binaries, updater, data_dir: Path) -> dict:
    return {
        "venv": not venv_python().exists(),
        "packages": missing_packages(data_dir, updater),
        "ffmpeg": not (binaries.find("ffmpeg") and binaries.find("ffprobe")),
    }


# ------------------------------------------------------------------ user interfaces
class ConsoleUI:
    def __init__(self, assume_yes: bool = False) -> None:
        self.assume_yes = assume_yes

    def ask(self, title: str, text: str) -> bool:
        print(f"\n== {title} ==\n{text}")
        if self.assume_yes:
            print("(--yes given, continuing)")
            return True
        return input("Continue? [Y/n] ").strip().lower() in ("", "y", "yes")

    def info(self, title: str, text: str) -> None:
        print(f"\n== {title} ==\n{text}")

    def error(self, title: str, text: str) -> None:
        print(f"\n!! {title} !!\n{text}", file=sys.stderr)

    def run_task(self, title: str, work) -> None:
        print(f"\n== {title} ==")

        def report(text=None, fraction=None, log=None):
            line = log if log is not None else text
            if line:
                print(line, flush=True)
        work(report)


class TkUI:
    """Small pop-up windows (tkinter ships with Python on Windows and macOS)."""

    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import messagebox, scrolledtext, ttk
        self.tk, self.mb, self.ttk, self.st = tk, messagebox, ttk, scrolledtext
        self.root = tk.Tk()
        self.root.withdraw()

    def ask(self, title: str, text: str) -> bool:
        return bool(self.mb.askyesno(title, text))

    def info(self, title: str, text: str) -> None:
        self.mb.showinfo(title, text)

    def error(self, title: str, text: str) -> None:
        self.mb.showerror(title, text)

    def run_task(self, title: str, work) -> None:
        tk, ttk = self.tk, self.ttk
        win = tk.Toplevel(self.root)
        win.title(title)
        win.geometry("560x320")
        win.protocol("WM_DELETE_WINDOW", lambda: None)          # no closing mid-install
        label = tk.StringVar(value="Starting...")
        ttk.Label(win, textvariable=label).pack(anchor="w", padx=12, pady=(12, 4))
        bar = ttk.Progressbar(win, mode="indeterminate")
        bar.pack(fill="x", padx=12)
        bar.start(12)
        log = self.st.ScrolledText(win, height=10, state="disabled", font=("Consolas", 9))
        log.pack(fill="both", expand=True, padx=12, pady=12)

        q: queue.Queue = queue.Queue()
        outcome: dict = {}

        def runner():
            try:
                work(lambda text=None, fraction=None, log=None: q.put((text, fraction, log)))
            except BaseException as exc:                          # shown to the user afterwards
                outcome["error"] = exc
            finally:
                q.put(None)

        def poll():
            try:
                while True:
                    item = q.get_nowait()
                    if item is None:
                        win.destroy()
                        return
                    text, fraction, line = item
                    if text:
                        label.set(text)
                    if fraction is not None:
                        bar.stop()
                        bar.configure(mode="determinate", maximum=100, value=fraction * 100)
                    if line:
                        log.configure(state="normal")
                        log.insert("end", line + "\n")
                        log.see("end")
                        log.configure(state="disabled")
            except queue.Empty:
                win.after(80, poll)

        threading.Thread(target=runner, daemon=True).start()
        win.after(80, poll)
        self.root.wait_window(win)
        if "error" in outcome:
            raise outcome["error"]


def make_ui(args):
    if not args.console:
        try:
            return TkUI()
        except Exception:                      # no tkinter or no display: fall back to the terminal
            pass
    return ConsoleUI(args.yes)


# ------------------------------------------------------------------ the work
def describe(missing: dict, can_download_ffmpeg: bool) -> list[str]:
    lines = []
    if missing["venv"]:
        lines.append("- A private Python environment for MediaForge (a '.venv' folder next to this file)")
    if missing["packages"]:
        lines.append(f"- Python packages: {', '.join(missing['packages'])}  (PySide6 is about 200 MB)")
    if missing["ffmpeg"]:
        lines.append("- ffmpeg + ffprobe (about 100 MB, downloaded from gyan.dev)" if can_download_ffmpeg
                     else "- ffmpeg + ffprobe  (NOT installed automatically on this system - "
                          "install with your package manager, e.g. 'brew install ffmpeg' / 'sudo apt install ffmpeg')")
    return lines


def pip_install(report) -> None:
    cmd = [str(venv_python()), "-m", "pip", "install", "--disable-pip-version-check",
           "--retries", "2", "--timeout", "20", "-r", str(ROOT / "requirements.txt")]
    report(text="Installing Python packages (this can take a few minutes)...", log="$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                            encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
    tail: list[str] = []
    for line in proc.stdout:
        line = line.rstrip()
        tail = (tail + [line])[-8:]
        report(log=line)
    if proc.wait() != 0:
        raise RuntimeError("Installing the Python packages failed (is the internet connection working?).\n\n"
                           "Last messages:\n" + "\n".join(tail))


def setup(missing: dict, updater, data_dir: Path):
    def work(report):
        if missing["venv"]:
            report(text="Creating the private Python environment...")
            try:
                venv.EnvBuilder(with_pip=True, symlinks=not IS_WIN).create(VENV)
            except Exception as exc:
                raise RuntimeError(f"Couldn't create the Python environment: {exc}\n\nOn Debian/Ubuntu try: "
                                   f"sudo apt install python3-venv") from None
        if missing["venv"] or missing["packages"]:
            pip_install(report)
        if missing["ffmpeg"] and updater.ffmpeg_install_supported():
            last = [0.0]

            def prog(done: int, total: int) -> None:
                if time.time() - last[0] > 0.25 or done == total:
                    last[0] = time.time()
                    frac = done / total if total else None
                    report(text=f"Downloading ffmpeg: {done / 1e6:.0f} of {total / 1e6:.0f} MB" if total
                           else f"Downloading ffmpeg: {done / 1e6:.0f} MB", fraction=frac)
            report(text="Downloading ffmpeg...")
            name = updater.install_ffmpeg(data_dir, prog)
            report(text="ffmpeg installed.", log=f"ffmpeg {name} installed")
    return work


def launch(ui, data_dir: Path) -> int:
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "startup.log"
    cmd = [str(venv_python()), str(ROOT / "main.py")]
    kwargs = {"creationflags": NO_WINDOW | 0x00000200} if IS_WIN else {"start_new_session": True}
    with open(log_path, "w", encoding="utf-8") as log:
        proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=log, stderr=log, **kwargs)
        time.sleep(2.5)                                   # long enough to catch an immediate crash
        code = proc.poll()
    if code not in (None, 0):
        tail = "\n".join(log_path.read_text(encoding="utf-8", errors="replace").splitlines()[-15:])
        ui.error(f"{APP} closed right after starting", f"Exit code {code}.\n\n{tail}\n\n(Full log: {log_path})")
        return 1
    return 0


def run(ui, args) -> int:
    sys.path.insert(0, str(ROOT))
    from mediaforge.core import binaries, updater       # standard-library-only modules
    data_dir = updater.default_data_dir()
    binaries.set_managed_dir(data_dir)

    missing = what_is_missing(binaries, updater, data_dir)
    lines = describe(missing, updater.ffmpeg_install_supported())
    needs_work = missing["venv"] or missing["packages"] or (missing["ffmpeg"] and updater.ffmpeg_install_supported())

    if args.check:
        ui.info(f"{APP} requirements", "Everything is installed." if not lines else "Missing:\n" + "\n".join(lines))
        return 1 if lines else 0

    if needs_work:
        if not ui.ask(f"{APP} setup", f"{APP} needs a few things before it can start:\n\n" + "\n".join(lines)
                      + "\n\nInstall them now?"):
            return 0
        ui.run_task(f"Setting up {APP}", setup(missing, updater, data_dir))
        missing = what_is_missing(binaries, updater, data_dir)
    elif lines:                                        # only ffmpeg, and we can't install it here
        ui.info(f"{APP}: ffmpeg missing", "\n".join(lines) + "\n\nMediaForge will still start; "
                "conversions need ffmpeg.")

    if args.no_launch:
        ui.info(f"{APP}", "Setup finished.")
        return 0
    return launch(ui, data_dir)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Check requirements, install what's missing, start MediaForge.")
    ap.add_argument("--check", action="store_true", help="only report what is missing")
    ap.add_argument("--yes", action="store_true", help="don't ask before installing (console mode)")
    ap.add_argument("--console", action="store_true", help="use the terminal instead of pop-up windows")
    ap.add_argument("--no-launch", action="store_true", help="set up, but don't start the program")
    args = ap.parse_args(argv)

    if sys.stdout is None:                              # pythonw has no console
        sys.stdout = sys.stderr = open(os.devnull, "w")
    ui = make_ui(args)
    if sys.version_info < MIN_PY:
        ui.error("Python too old", f"{APP} needs Python {MIN_PY[0]}.{MIN_PY[1]} or newer "
                                   f"(this is {sys.version.split()[0]}). Get it from https://www.python.org/downloads/")
        return 2
    try:
        return run(ui, args)
    except Exception as exc:
        try:
            sys.path.insert(0, str(ROOT))
            from mediaforge.core import updater
            folder = updater.default_data_dir()
            folder.mkdir(parents=True, exist_ok=True)
            (folder / "launcher.log").write_text(traceback.format_exc(), encoding="utf-8")
        except Exception:
            pass
        ui.error(f"{APP} couldn't start", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
