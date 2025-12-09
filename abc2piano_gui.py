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
from typing import Dict, Any, Optional, Tuple

import subprocess
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import mido
import ffmpeg

APP_NAME = "abc2piano"
SF2_FILENAME = "YDP-GrandPiano-20160804.sf2"

# Reverb presets:
#   key: human label shown in the combobox
#   value: None -> no reverb
#           ("filter_name", [arg1, arg2, ...]) -> ffmpeg audio filter
REVERB_PRESETS: Dict[str, Optional[Tuple[str, list[float | int | str]]]] = {
    "None": None,
    "Small room (aecho)": ("aecho", [0.8, 0.9, 60, 0.4]),
    "Large hall (aecho)": ("aecho", [0.8, 0.88, 1200, 0.3]),
}

# Output format presets:
#   key: human label
#   value: dict with ffmpeg settings + default extension
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


def get_default_soundfont_path() -> Path:
    return get_resource_dir() / SF2_FILENAME


# ---------------------------------------------------------------------------
# Audio pipeline helpers
# ---------------------------------------------------------------------------

def abc_to_midi(abc_path: Path, midi_path: Path) -> None:
    """
    Convert ABC file to MIDI using the external `abc2midi` tool (from abcmidi).

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
    Take a dry WAV file and produce final audio with optional reverb
    and encoding (WAV/MP3/Opus) via ffmpeg.
    """
    if not dry_wav.exists():
        raise FileNotFoundError(f"Dry WAV not found: {dry_wav}")

    if output_preset_name not in OUTPUT_PRESETS:
        raise ValueError(f"Unknown output preset: {output_preset_name}")

    preset = OUTPUT_PRESETS[output_preset_name]
    codec = preset["codec"]
    bitrate = preset["bitrate"]

    stream = ffmpeg.input(str(dry_wav))

    # Reverb
    reverb_spec = REVERB_PRESETS.get(reverb_preset_name)
    if reverb_spec is not None:
        filter_name, args = reverb_spec
        stream = stream.filter_(filter_name, *args)

    kwargs: Dict[str, Any] = {"acodec": codec}
    if bitrate is not None:
        kwargs["audio_bitrate"] = bitrate

    (
        stream
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

        abc_to_midi(abc_path, midi_path)
        midi_to_wav(midi_path, dry_wav, soundfont_path)
        process_with_ffmpeg(dry_wav, out_path, reverb_preset_name, output_preset_name)


# ---------------------------------------------------------------------------
# Tk GUI
# ---------------------------------------------------------------------------

class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("ABC → Piano Audio")

        self.abc_path_var = tk.StringVar()
        self.reverb_var = tk.StringVar(value="None")
        self.output_preset_var = tk.StringVar(value="WAV (44.1 kHz)")

        self.status_var = tk.StringVar(value="Ready.")
        self.export_button: ttk.Button | None = None

        self._build_ui()

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

        # Export button
        self.export_button = ttk.Button(frame, text="Export…", command=self.on_export)
        self.export_button.grid(row=3, column=0, columnspan=3, pady=(15, 0))

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
        path = filedialog.askopenfilename(
            title="Select ABC file",
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

        out_path_str = filedialog.asksaveasfilename(
            title="Save audio as",
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
        # Optionally change cursor
        self.root.configure(cursor="watch" if busy else "")
        self.root.update_idletasks()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def main() -> None:
    root = tk.Tk()
    app = App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
