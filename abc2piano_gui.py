#!/usr/bin/env python3
"""
abc2piano - simple Tk GUI to convert ABC notation to piano audio.
"""

import tkinter as tk
from tkinter import ttk
from pathlib import Path
import sys
import os

APP_NAME = "abc2piano"
SF2_FILENAME = "YDP-GrandPiano-20160804.sf2"

def get_resource_dir() -> Path:
    # When frozen with PyInstaller, data files are in sys._MEIPASS
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "resources"
    # Running from source
    return Path(__file__).resolve().parent / "resources"


def get_default_soundfont_path() -> Path:
    return get_resource_dir() / SF2_FILENAME

def main() -> None:
    root = tk.Tk()
    root.title("abc2piano")
    ttk.Label(root, text="Hello from abc2piano").pack(padx=20, pady=20)
    root.mainloop()

if __name__ == "__main__":
    main()
