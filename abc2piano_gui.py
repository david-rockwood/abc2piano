#!/usr/bin/env python3
"""
abc2piano - simple Tk GUI to convert ABC notation into piano audio.

Pipeline:
    ABC file -> MIDI (music21) -> dry WAV (pyfluidsynth + SF2) -> final
    format with optional reverb (ffmpeg).
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path
import fnmatch
from typing import Dict, Any, Optional

import subprocess
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter import font as tkfont

import mido
import ffmpeg


def open_with_default_app(path: Path) -> None:
    """Open a file with the platform's default application."""
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    opener = "open" if sys.platform == "darwin" else "xdg-open"
    subprocess.Popen([opener, str(path)])

APP_NAME = "abc2piano"
SF2_FILENAME = "YDP-GrandPiano-20160804.sf2"
ICON_PNG_FILENAME = "abc2piano.png"
ICON_ICO_FILENAME = "abc2piano.ico"

ReverbSpec = Dict[str, Any]

REVERB_PRESETS: Dict[str, Optional[ReverbSpec]] = {
    "None": None,

    "Dry studio": {
        "type": "afir",
        "impulse": "IRx125_01A_dry-studio.wav",
    },
    "Small room": {
        "type": "afir",
        "impulse": "IRx250_01A_small-room.wav",
    },
    "Concert hall": {
        "type": "afir",
        "impulse": "IRx500_01A_concert-hall.wav",
    },
    "Wide hall": {
        "type": "afir",
        "impulse": "IRx500_02A_wide-hall.wav",
    },
    "Grand hall": {
        "type": "afir",
        "impulse": "IRx1000_01A_grand-hall.wav",
    },
    "Cinematic hall": {
        "type": "afir",
        "impulse": "IRx1000_02A_cinematic-hall.wav",
    },
}

# ---------------------------------------------------------------------------
# Global reverb tuning (baked defaults)
# ---------------------------------------------------------------------------

AFIR_DRY_GAIN: float = 1.0       # AFIR input gain
AFIR_WET_GAIN: float = 1.0       # AFIR output gain
MIX_DRY_WEIGHT: float = 1.0      # parallel dry branch weight
MIX_WET_WEIGHT: float = 1.0      # parallel wet branch weight
POST_VOLUME_GAIN: float = 2.8    # makeup gain after mix
USE_LIMITER: bool = True         # soft limiter on final output

OUTPUT_PRESETS: Dict[str, Dict[str, Any]] = {
    "WAV (44.1 kHz)": {
        "ext": ".wav",
        "codec": "pcm_s16le",
        "bitrate": None,  # PCM, no bitrate
    },
    "MP3 192 kbps": {
        "ext": ".mp3",
        "codec": "libmp3lame",
        "bitrate": "192k",
    },
    "Opus 96 kbps": {
        "ext": ".opus",
        "codec": "libopus",
        "bitrate": "96k",
    },
}


# ---------------------------------------------------------------------------
# Resource resolution (works for both source + PyInstaller)
# ---------------------------------------------------------------------------

def get_resource_dir() -> Path:
    """
    Return the directory where bundled resources live.

    - When running from PyInstaller, data files are unpacked into sys._MEIPASS.
    - When running from source, they live in ./resources beside this file.
    """
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / "resources"
    return Path(__file__).resolve().parent / "resources"


def set_window_icon(root: tk.Tk) -> None:
    """Set the window/taskbar icon on all supported platforms."""
    resource_dir = get_resource_dir()

    png_path = resource_dir / ICON_PNG_FILENAME
    try:
        icon_png = tk.PhotoImage(file=str(png_path))
    except tk.TclError:
        icon_png = None
    else:
        root.iconphoto(True, icon_png)
        # Prevent garbage collection of the image
        root._abc2piano_icon = icon_png  # type: ignore[attr-defined]

    ico_path = resource_dir / ICON_ICO_FILENAME
    if os.name == "nt" and ico_path.exists():
        try:
            root.iconbitmap(default=str(ico_path))
        except tk.TclError:
            pass


class FileBrowserDialog(tk.Toplevel):
    def __init__(
        self,
        parent: tk.Tk,
        title: str,
        mode: str,
        filetypes: list[tuple[str, str]] | None = None,
        defaultextension: str | None = None,
    ) -> None:
        super().__init__(parent)
        self.parent = parent
        self.mode = mode
        self.filetypes = filetypes or []
        self.defaultextension = defaultextension
        self.result: Path | None = None
        self.working_dir = Path.cwd()

        self.title(title)
        self.transient(parent)
        self.grab_set()

        self.filename_var = tk.StringVar()
        self.show_hidden_var = tk.BooleanVar(value=False)

        self._build_ui()
        self._refresh_file_list()

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)
        self.wait_window(self)

    # --- UI construction ---------------------------------------------------
    def _build_ui(self) -> None:
        container = ttk.Frame(self, padding=10)
        container.grid(row=0, column=0, sticky="nsew")
        self.columnconfigure(0, weight=1)
        self.rowconfigure(0, weight=1)
        container.columnconfigure(0, weight=1)

        ttk.Label(container, text="Working directory:").grid(row=0, column=0, sticky="w")
        self.cwd_label = ttk.Label(container, text=str(self.working_dir), anchor="w")
        self.cwd_label.grid(row=1, column=0, sticky="we", pady=(0, 5))

        tree_frame = ttk.Frame(container)
        tree_frame.grid(row=2, column=0, sticky="nsew")
        container.rowconfigure(2, weight=1)
        tree_frame.columnconfigure(0, weight=1)

        style = ttk.Style(self)
        tree_font = tkfont.nametofont(style.lookup("Treeview", "font") or "TkDefaultFont")
        row_height = tree_font.metrics("linespace") + 6
        style.configure("FileBrowser.Treeview", rowheight=row_height)

        self.tree = ttk.Treeview(
            tree_frame,
            show="tree",
            selectmode="browse",
            style="FileBrowser.Treeview",
        )
        vsb = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.grid(row=0, column=0, sticky="nsew")
        vsb.grid(row=0, column=1, sticky="ns")
        tree_frame.rowconfigure(0, weight=1)

        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.tree.bind("<Double-1>", self._on_double_click)
        # Support scrolling with mouse wheel and middle button events on X11
        self.tree.bind("<MouseWheel>", self._on_mousewheel)
        self.tree.bind("<Button-4>", self._on_mousewheel)
        self.tree.bind("<Button-5>", self._on_mousewheel)

        entry_frame = ttk.Frame(container)
        entry_frame.grid(row=3, column=0, sticky="we", pady=(8, 4))
        entry_frame.columnconfigure(1, weight=1)
        ttk.Label(entry_frame, text="File name:").grid(row=0, column=0, padx=(0, 5))
        entry = ttk.Entry(entry_frame, textvariable=self.filename_var)
        entry.grid(row=0, column=1, sticky="we")
        entry.bind("<Return>", lambda event: self._on_confirm())

        options_frame = ttk.Frame(container)
        options_frame.grid(row=4, column=0, sticky="we", pady=(0, 8))
        ttk.Checkbutton(
            options_frame,
            text="Show hidden files",
            variable=self.show_hidden_var,
            command=self._refresh_file_list,
        ).grid(row=0, column=0, sticky="w")

        button_frame = ttk.Frame(container)
        button_frame.grid(row=5, column=0, sticky="e")
        ttk.Button(button_frame, text="Cancel", command=self._on_cancel).grid(row=0, column=0, padx=(0, 5))
        action_label = "Open" if self.mode == "open" else "Save"
        ttk.Button(button_frame, text=action_label, command=self._on_confirm).grid(row=0, column=1)

    # --- Event handlers ----------------------------------------------------
    def _on_select(self, event: tk.Event[tk.Treeview]) -> None:
        selection = self.tree.selection()
        if not selection:
            return
        item_id = selection[0]
        name = self.tree.item(item_id, "text")
        if name == "..":
            self.filename_var.set("")
        else:
            self.filename_var.set(name.rstrip("/"))

    def _on_double_click(self, event: tk.Event[tk.Treeview]) -> None:
        item_id = self.tree.focus()
        if not item_id:
            return
        name = self.tree.item(item_id, "text")
        if name == "..":
            self.working_dir = self.working_dir.parent
            self._refresh_file_list()
            return

        path = self.working_dir / name.rstrip("/")
        if path.is_dir():
            self.working_dir = path
            self._refresh_file_list()
        else:
            self.filename_var.set(name)
            self._on_confirm()

    def _on_mousewheel(self, event: tk.Event[tk.Treeview]) -> None:
        if event.num == 4:  # X11 scroll up
            delta = -1
        elif event.num == 5:  # X11 scroll down
            delta = 1
        else:
            delta = -1 * (event.delta // 120)
        self.tree.yview_scroll(delta, "units")
        return "break"

    def _on_confirm(self) -> None:
        filename = self.filename_var.get().strip()
        if not filename:
            messagebox.showerror("Error", "Please select or enter a file name.")
            return

        candidate = self.working_dir / filename
        if candidate.is_dir():
            self.working_dir = candidate
            self.filename_var.set("")
            self._refresh_file_list()
            return

        if self.mode == "open":
            if not candidate.exists():
                messagebox.showerror("Error", f"File does not exist:\n{candidate}")
                return
            if not self._matches_filetypes(candidate):
                messagebox.showerror("Error", "Selected file type is not allowed.")
                return
        else:
            if self.defaultextension and not candidate.suffix:
                candidate = candidate.with_suffix(self.defaultextension)

        self.result = candidate
        self._close()

    def _on_cancel(self) -> None:
        self.result = None
        self._close()

    # --- Helpers -----------------------------------------------------------
    def _close(self) -> None:
        self.grab_release()
        self.destroy()

    def _matches_filetypes(self, path: Path) -> bool:
        if not self.filetypes:
            return True
        for _label, pattern in self.filetypes:
            if pattern in ("*", "*.*"):
                return True
            if fnmatch.fnmatch(path.name, pattern):
                return True
        return False

    def _refresh_file_list(self) -> None:
        self.cwd_label.configure(text=str(self.working_dir))
        self.tree.delete(*self.tree.get_children())

        if self.working_dir.parent != self.working_dir:
            self.tree.insert("", "end", text="..")

        entries = sorted(self.working_dir.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        for entry in entries:
            if not self.show_hidden_var.get() and entry.name.startswith("."):
                continue
            if entry.is_file() and not self._matches_filetypes(entry):
                continue
            label = f"{entry.name}/" if entry.is_dir() else entry.name
            self.tree.insert("", "end", text=label)


def ask_workdir_file(
    parent: tk.Tk,
    title: str,
    mode: str,
    filetypes: list[tuple[str, str]] | None = None,
    defaultextension: str | None = None,
) -> str:
    dialog = FileBrowserDialog(
        parent=parent,
        title=title,
        mode=mode,
        filetypes=filetypes,
        defaultextension=defaultextension,
    )
    return str(dialog.result) if dialog.result is not None else ""


def get_default_soundfont_path() -> Path:
    return get_resource_dir() / SF2_FILENAME

def get_impulse_response_path(filename: str) -> Path:
    """
    Return the full path to an impulse response file stored under
    resources/impulses/.
    """
    return get_resource_dir() / "impulses" / filename


# ---------------------------------------------------------------------------
# Audio pipeline helpers
# ---------------------------------------------------------------------------

def abc_to_midi(abc_path: Path, midi_path: Path) -> Path:
    """
    Convert ABC file to MIDI using the external `abc2midi` tool (from abcmidi).

    Returns the path of the first generated MIDI file. abc2midi can emit
    numbered files (foo1.mid, foo2.mid, …) even when an explicit ``-o`` target
    is provided, so we scan for the produced file instead of assuming the
    exact name.

    Requires `abc2midi` to be installed and on PATH.
    On Debian/Ubuntu: sudo apt-get install abcmidi
    """
    if not abc_path.exists():
        raise FileNotFoundError(f"ABC file not found: {abc_path}")

    try:
        # abc2midi infile.abc -o outfile.mid
        result = subprocess.run(
            ["abc2midi", str(abc_path), "-o", str(midi_path)],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # If you ever want to see diagnostics, result.stdout has abc2midi’s text.
        # print(result.stdout)
    except FileNotFoundError:
        raise RuntimeError(
            "abc2midi (from the abcmidi package) is not installed or not on PATH.\n"
            "On Debian/Ubuntu, install it with:\n\n"
            "    sudo apt-get install abcmidi\n"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "abc2midi failed while converting ABC to MIDI.\n\n"
            f"Command: {' '.join(e.cmd)}\n"
            f"Exit code: {e.returncode}\n"
            f"Output:\n{e.stdout}"
        )

    # abc2midi may append tune numbers (e.g., temp1.mid) even when given an
    # explicit output path. Pick the first generated MIDI in the target
    # directory that matches the requested stem.
    if midi_path.exists():
        return midi_path

    parent = midi_path.parent
    stem = midi_path.stem
    numbered_midis = sorted(parent.glob(f"{stem}*.mid"))
    if numbered_midis:
        return numbered_midis[0]

    raise FileNotFoundError(
        "abc2midi did not produce a MIDI file.\n\n"
        f"Expected output at: {midi_path}\n"
        "If your ABC contains multiple tunes, abc2midi may write numbered files."
    )

def midi_to_wav(midi_path: Path, wav_path: Path, soundfont_path: Path) -> None:
    """
    Render a MIDI file to a dry WAV file using the external `fluidsynth` CLI.

    - Uses 44100 Hz sample rate.
    - Uses the given SF2 SoundFont.
    - Requires `fluidsynth` to be installed and on PATH.
      On Debian/Ubuntu: sudo apt-get install fluidsynth
    """
    if not midi_path.exists():
        raise FileNotFoundError(f"MIDI file not found: {midi_path}")

    if not soundfont_path.exists():
        raise FileNotFoundError(
            f"SoundFont not found: {soundfont_path}\n\n"
            "Make sure the YDP Grand Piano SF2 has been downloaded "
            "into the resources/ directory or bundled with the app."
        )

    cmd = [
        "fluidsynth",
        "-F", str(wav_path),
        "-r", "44100",
        "-g", "0.8",          # a bit louder than the default 0.2
        "-i", "-n",           # no interactive shell, no MIDI input device
        "-T", "wav",          # ensure the file format really is WAV
        str(soundfont_path),
        str(midi_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Uncomment if you want to see what fluidsynth says:
        # print(result.stdout)
    except FileNotFoundError:
        raise RuntimeError(
            "fluidsynth is not installed or not on PATH.\n"
            "On Debian/Ubuntu, install it with:\n\n"
            "    sudo apt-get install fluidsynth\n"
        )
    except subprocess.CalledProcessError as e:
        raise RuntimeError(
            "fluidsynth failed while converting MIDI to WAV.\n\n"
            f"Command: {' '.join(e.cmd)}\n"
            f"Exit code: {e.returncode}\n"
            f"Output:\n{e.stdout}"
        )

def process_with_ffmpeg(
    dry_wav: Path,
    out_path: Path,
    reverb_preset_name: str,
    output_preset_name: str,
) -> None:
    """
    Take a dry WAV file and produce final audio with optional convolution
    reverb and encoding (WAV/MP3/Opus) via ffmpeg.

    - If reverb_preset is None -> pass-through dry audio.
    - If reverb_preset uses AFIR -> build a parallel dry+wet mix:
          dry_in ──┬─► AFIR (wet branch)
                  └─► direct (dry branch)
          then AMIX, volume, optional limiter.

    The tuning is controlled by the global constants:
        AFIR_DRY_GAIN, AFIR_WET_GAIN,
        MIX_DRY_WEIGHT, MIX_WET_WEIGHT,
        POST_VOLUME_GAIN, USE_LIMITER.
    """
    if not dry_wav.exists():
        raise FileNotFoundError(f"Dry WAV not found: {dry_wav}")

    if output_preset_name not in OUTPUT_PRESETS:
        raise ValueError(f"Unknown output preset: {output_preset_name}")

    preset = OUTPUT_PRESETS[output_preset_name]
    codec = preset["codec"]
    bitrate = preset["bitrate"]

    reverb_spec = REVERB_PRESETS.get(reverb_preset_name)

    # --- No reverb: just pass the dry audio straight through ---------------
    if reverb_spec is None:
        audio_stream = ffmpeg.input(str(dry_wav)).audio

    else:
        rtype = reverb_spec.get("type")
        if rtype != "afir":
            raise ValueError(f"Unknown reverb preset type: {rtype!r}")

        impulse_name = reverb_spec.get("impulse")
        if not impulse_name:
            raise ValueError(
                f"AFIR preset '{reverb_preset_name}' is missing 'impulse'"
            )

        ir_path = get_impulse_response_path(impulse_name)
        if not ir_path.exists():
            raise FileNotFoundError(
                f"Impulse response not found for preset '{reverb_preset_name}': {ir_path}"
            )

        # Inputs
        base_in = ffmpeg.input(str(dry_wav)).audio
        ir_in = ffmpeg.input(str(ir_path)).audio

        # Split dry input into two branches:
        #   - dry_for_conv -> AFIR (wet)
        #   - dry_for_mix  -> direct dry path
        split = base_in.filter_multi_output("asplit", 2)
        dry_for_conv = split[0]
        dry_for_mix = split[1]

        # Build AFIR options (clamp to valid [0, 10] range)
        afir_options: Dict[str, Any] = {
            "dry": max(0.0, min(10.0, AFIR_DRY_GAIN)),
            "wet": max(0.0, min(10.0, AFIR_WET_GAIN)),
        }

        wet = ffmpeg.filter([dry_for_conv, ir_in], "afir", **afir_options)

        # Mix original dry branch with wet branch
        mixed = ffmpeg.filter(
            [dry_for_mix, wet],
            "amix",
            inputs=2,
            weights=f"{MIX_DRY_WEIGHT} {MIX_WET_WEIGHT}",
        )

        # Apply overall volume and optional soft limiter
        audio_stream = mixed.filter_("volume", POST_VOLUME_GAIN)
        if USE_LIMITER:
            audio_stream = audio_stream.filter_("alimiter")

    # --- Output encoding ---------------------------------------------------
    kwargs: Dict[str, Any] = {"acodec": codec}
    if bitrate is not None:
        kwargs["audio_bitrate"] = bitrate

    (
        audio_stream
        .output(str(out_path), **kwargs)
        .overwrite_output()
        .run()
    )

def export_abc_to_audio(
    abc_path: Path,
    out_path: Path,
    reverb_preset_name: str,
    output_preset_name: str,
    soundfont_path: Path,
) -> None:
    """
    High-level pipeline: ABC file -> temp MIDI -> temp dry WAV -> final audio.
    """
    with tempfile.TemporaryDirectory() as tmpdir_str:
        tmpdir = Path(tmpdir_str)
        midi_path = tmpdir / "temp.mid"
        dry_wav = tmpdir / "dry.wav"

        midi_path = abc_to_midi(abc_path, midi_path)
        midi_to_wav(midi_path, dry_wav, soundfont_path)
        process_with_ffmpeg(dry_wav, out_path, reverb_preset_name, output_preset_name)
        

# ---------------------------------------------------------------------------
# Tk GUI
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ABC2piano v0.0.3")

        self.abc_path_var = tk.StringVar()
        self.reverb_var = tk.StringVar(value="Concert hall")
        self.output_preset_var = tk.StringVar(value="WAV (44.1 kHz)")

        self.status_var = tk.StringVar(value="Ready.")
        self.export_button: ttk.Button | None = None
        self.play_button: ttk.Button | None = None
        self.temp_play_file: Path | None = None

        self._build_ui()
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # --- UI construction ---------------------------------------------------

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        frame = ttk.Frame(self.root, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        frame.columnconfigure(1, weight=1)

        # ABC file row
        ttk.Label(frame, text="ABC file:").grid(row=0, column=0, sticky="w")
        entry = ttk.Entry(frame, textvariable=self.abc_path_var, width=50)
        entry.grid(row=0, column=1, sticky="we", padx=(5, 5))
        ttk.Button(frame, text="Open…", command=self.on_open).grid(row=0, column=2, padx=(5, 0))

        # Reverb preset row
        ttk.Label(frame, text="Reverb:").grid(row=1, column=0, sticky="w", pady=(10, 0))
        reverb_combo = ttk.Combobox(
            frame,
            textvariable=self.reverb_var,
            values=list(REVERB_PRESETS.keys()),
            state="readonly",
        )
        reverb_combo.grid(row=1, column=1, sticky="we", pady=(10, 0))

        # Output preset row
        ttk.Label(frame, text="Output format:").grid(row=2, column=0, sticky="w", pady=(10, 0))
        out_combo = ttk.Combobox(
            frame,
            textvariable=self.output_preset_var,
            values=list(OUTPUT_PRESETS.keys()),
            state="readonly",
        )
        out_combo.grid(row=2, column=1, sticky="we", pady=(10, 0))

        # Play / Export buttons
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=3, column=0, columnspan=3, pady=(15, 0), sticky="e")

        self.play_button = ttk.Button(button_frame, text="Play", command=self.on_play)
        self.play_button.grid(row=0, column=0, padx=(0, 5))

        self.export_button = ttk.Button(button_frame, text="Export…", command=self.on_export)
        self.export_button.grid(row=0, column=1)

        # Status bar
        status_label = ttk.Label(
            self.root,
            textvariable=self.status_var,
            anchor="w",
            relief="sunken",
            padding=(5, 2),
        )
        status_label.grid(row=1, column=0, sticky="we")

    # --- UI actions --------------------------------------------------------
    def on_open(self) -> None:
        path = ask_workdir_file(
            parent=self.root,
            title="Select ABC file",
            mode="open",
            filetypes=[
                ("ABC files", "*.abc"),
                ("Text files", "*.txt"),
                ("All files", "*.*"),
            ],
        )
        if path:
            self.abc_path_var.set(path)
            self.status_var.set(f"Selected ABC file: {path}")

    def on_export(self) -> None:
        abc_path_str = self.abc_path_var.get().strip()
        if not abc_path_str:
            messagebox.showerror("Error", "Please select an ABC file first.")
            return

        abc_path = Path(abc_path_str)
        if not abc_path.exists():
            messagebox.showerror("Error", f"ABC file does not exist:\n{abc_path}")
            return

        # Determine default extension from output preset
        output_preset_name = self.output_preset_var.get()
        preset = OUTPUT_PRESETS.get(output_preset_name)
        if preset is None:
            messagebox.showerror("Error", f"Unknown output preset: {output_preset_name}")
            return

        default_ext = preset["ext"]

        out_path_str = ask_workdir_file(
            parent=self.root,
            title="Save audio as",
            mode="save",
            defaultextension=default_ext,
            filetypes=[
                ("Audio files", f"*{default_ext}"),
                ("All files", "*.*"),
            ],
        )
        if not out_path_str:
            return

        out_path = Path(out_path_str)

        # Locate soundfont
        soundfont_path = get_default_soundfont_path()

        # Run pipeline (synchronously, simple first version)
        self._set_busy(True)
        self.status_var.set("Rendering… this may take a moment.")
        self.root.update_idletasks()

        try:
            export_abc_to_audio(
                abc_path=abc_path,
                out_path=out_path,
                reverb_preset_name=self.reverb_var.get(),
                output_preset_name=output_preset_name,
                soundfont_path=soundfont_path,
            )
        except Exception as e:
            messagebox.showerror("Error", f"Failed to export audio:\n\n{e}")
            self.status_var.set("Error during export.")
        else:
            self.status_var.set(f"Exported audio to: {out_path}")
            messagebox.showinfo("Done", f"Exported audio to:\n{out_path}")
        finally:
            self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        if self.export_button is not None:
            self.export_button.configure(state="disabled" if busy else "normal")
        if self.play_button is not None:
            self.play_button.configure(state="disabled" if busy else "normal")
        # Optionally change cursor
        self.root.configure(cursor="watch" if busy else "")
        self.root.update_idletasks()

    def _delete_temp_play_file(self) -> None:
        if self.temp_play_file and self.temp_play_file.exists():
            try:
                self.temp_play_file.unlink()
            except OSError:
                pass
        self.temp_play_file = None

    def on_play(self) -> None:
        abc_path_str = self.abc_path_var.get().strip()
        if not abc_path_str:
            messagebox.showerror("Error", "Please select an ABC file first.")
            return

        abc_path = Path(abc_path_str)
        if not abc_path.exists():
            messagebox.showerror("Error", f"ABC file does not exist:\n{abc_path}")
            return

        output_preset_name = self.output_preset_var.get()
        preset = OUTPUT_PRESETS.get(output_preset_name)
        if preset is None:
            messagebox.showerror("Error", f"Unknown output preset: {output_preset_name}")
            return

        ext = preset["ext"]

        self._delete_temp_play_file()
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as tmp:
            temp_out_path = Path(tmp.name)

        soundfont_path = get_default_soundfont_path()

        self._set_busy(True)
        self.status_var.set("Rendering preview…")
        self.root.update_idletasks()

        try:
            export_abc_to_audio(
                abc_path=abc_path,
                out_path=temp_out_path,
                reverb_preset_name=self.reverb_var.get(),
                output_preset_name=output_preset_name,
                soundfont_path=soundfont_path,
            )
            self.temp_play_file = temp_out_path
        except Exception as e:
            self._delete_temp_play_file()
            messagebox.showerror("Error", f"Failed to render preview:\n\n{e}")
            self.status_var.set("Error during preview.")
        else:
            self.status_var.set(f"Playing: {temp_out_path}")
            open_with_default_app(temp_out_path)
        finally:
            self._set_busy(False)

    def on_close(self) -> None:
        self._delete_temp_play_file()
        self.root.destroy()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    set_window_icon(root)
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
