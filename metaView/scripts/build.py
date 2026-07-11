"""Build a native metaView application with PyInstaller."""

from __future__ import annotations

import platform
from pathlib import Path
import PyInstaller.__main__

ROOT = Path(__file__).resolve().parents[1]
ENTRY = ROOT / "main.py"
ASSETS = ROOT / "src" / "metaview" / "assets"
SYSTEM = platform.system()

args = [
    str(ENTRY),
    "--name=metaView",
    "--windowed",
    "--noconfirm",
    "--clean",
    "--paths",
    str(ROOT / "src"),
    "--add-data",
    f"{ASSETS}:assets",
]

if SYSTEM == "Windows":
    args.extend(["--icon", str(ASSETS / "metaview.ico")])
elif SYSTEM == "Darwin":
    # PyInstaller/Pillow can convert the PNG for the app bundle.
    args.extend(["--icon", str(ASSETS / "metaview.png"), "--osx-bundle-identifier", "uk.co.mhammond.metaview"])

PyInstaller.__main__.run(args)
