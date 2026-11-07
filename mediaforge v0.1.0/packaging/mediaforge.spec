# -*- mode: python ; coding: utf-8 -*-
# PyInstaller spec for MediaForge.   Use packaging/build_windows.ps1 rather than calling this directly.
#   MEDIAFORGE_ONEFILE=1  -> a single MediaForge.exe   (default: a folder, which starts faster)
import os

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
ONEFILE = os.environ.get("MEDIAFORGE_ONEFILE") == "1"
ICON = os.path.join(ROOT, "assets", "icon.ico")

datas = [(os.path.join(ROOT, "assets"), "assets")]
hiddenimports = []

# yt-dlp is imported lazily (inside functions) and ships ~1000 extractor modules.
hiddenimports += collect_submodules("yt_dlp")
for pkg in ("yt_dlp", "certifi"):          # certifi = HTTPS certificate bundle
    datas += collect_data_files(pkg)
try:                                       # lets importlib.metadata report the bundled yt-dlp version
    from PyInstaller.utils.hooks import copy_metadata
    datas += copy_metadata("yt-dlp")
except Exception:
    pass

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "pytest"],
)
pyz = PYZ(a.pure)

icon = ICON if os.path.exists(ICON) else None

if ONEFILE:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [],
              name="MediaForge", console=False, upx=False, icon=icon)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True,
              name="MediaForge", console=False, upx=False, icon=icon)
    coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="MediaForge")
