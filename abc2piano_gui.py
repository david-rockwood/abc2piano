#!/usr/bin/env python3
"""
abc2piano - simple Tk GUI to convert ABC notation to piano audio.
"""

import tkinter as tk
from tkinter import ttk

def main() -> None:
    root = tk.Tk()
    root.title("abc2piano")
    ttk.Label(root, text="Hello from abc2piano").pack(padx=20, pady=20)
    root.mainloop()

if __name__ == "__main__":
    main()
