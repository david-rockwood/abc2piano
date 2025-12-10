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
# Reverb presets:
#   key: human label shown in the combobox
#   value:
#       None -> no reverb
#       dict with:
#           "type": "afir"
#           "impulse": filename under resources/impulses/
#           "options": dict of afir options (dry/wet mix, etc.)
ReverbSpec = Dict[str, Any]

REVERB_PRESETS: Dict[str, Optional[ReverbSpec]] = {
    "None": None,

    "Dry studio": {
        "type": "afir",
        "impulse": "IRx125_01A_dry-studio.wav",
        "options": {"dry": 1.2, "wet": 0.6},
    },
    "Small room": {
        "type": "afir",
        "impulse": "IRx250_01A_small-room.wav",
        "options": {"dry": 1.0, "wet": 0.9},
    },
    "Concert hall": {
        "type": "afir",
        "impulse": "IRx500_01A_concert-hall.wav",
        "options": {"dry": 4.0, "wet": 1.0},
    },
    "Wide hall": {
        "type": "afir",
        "impulse": "IRx500_02A_wide-hall.wav",
        "options": {"dry": 0.9, "wet": 1.2},
    },
    "Grand hall": {
        "type": "afir",
        "impulse": "IRx1000_01A_grand-hall.wav",
        "options": {"dry": 0.8, "wet": 1.3},
    },
    "Cinematic hall": {
        "type": "afir",
        "impulse": "IRx1000_02A_cinematic-hall.wav",
        "options": {"dry": 0.7, "wet": 1.4},
    },
}
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

def get_impulse_response_path(filename: str) -> Path:
    """
    Return the full path to an impulse response file stored under
    resources/impulses/.
    """
    return get_resource_dir() / "impulses" / filename


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
    advanced_reverb: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Take a dry WAV file and produce final audio with optional convolution
    reverb and encoding (WAV/MP3/Opus) via ffmpeg.

    - If reverb_preset is None -> pass-through dry audio.
    - If reverb_preset uses AFIR -> build a parallel dry+wet mix:
          dry_in ──┬─► AFIR (wet branch)
                  └─► direct (dry branch)
          then AMIX, volume, optional limiter.

    advanced_reverb (if provided) is a dict with keys:
        - dry: float        (AFIR input gain, 0–10)
        - wet: float        (AFIR output gain, 0–10)
        - post_volume: float (overall gain after mix)
        - mix_dry: float    (weight for dry branch in amix)
        - mix_wet: float    (weight for wet branch in amix)
        - use_limiter: bool (whether to insert alimiter at end)
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
        # Defaults if advanced_reverb is not supplied
        if advanced_reverb is None:
            advanced_reverb = {}

        dry_gain = float(advanced_reverb.get("dry", 4.0))
        wet_gain = float(advanced_reverb.get("wet", 1.0))
        post_volume = float(advanced_reverb.get("post_volume", 3.0))
        mix_dry = float(advanced_reverb.get("mix_dry", 1.0))
        mix_wet = float(advanced_reverb.get("mix_wet", 1.0))
        use_limiter = bool(advanced_reverb.get("use_limiter", True))

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


        # Build AFIR options (clamp to valid [0, 10] range just in case)
        afir_options: Dict[str, Any] = {
            "dry": max(0.0, min(10.0, dry_gain)),
            "wet": max(0.0, min(10.0, wet_gain)),
        }

        wet = ffmpeg.filter([dry_for_conv, ir_in], "afir", **afir_options)

        # Mix original dry branch with wet branch
        # 'amix' with weights = "mix_dry mix_wet"
        mixed = ffmpeg.filter(
            [dry_for_mix, wet],
            "amix",
            inputs=2,
            weights=f"{mix_dry} {mix_wet}",
        )

        # Apply overall volume and optional soft limiter
        audio_stream = mixed.filter_("volume", float(post_volume))
        if use_limiter:
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
    advanced_reverb: Optional[Dict[str, Any]] = None,
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
        process_with_ffmpeg(
            dry_wav,
            out_path,
            reverb_preset_name,
            output_preset_name,
            advanced_reverb=advanced_reverb,
        )
        

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

        # Advanced reverb tuning (secret) ------------------------------
        self.adv_dry = tk.DoubleVar(value=4.0)
        self.adv_wet = tk.DoubleVar(value=1.0)
        self.adv_post_volume = tk.DoubleVar(value=3.0)
        self.adv_mix_dry = tk.DoubleVar(value=1.0)
        self.adv_mix_wet = tk.DoubleVar(value=1.0)
        self.adv_use_limiter = tk.BooleanVar(value=True)

        self._build_ui()

        self.root.bind("<Control-Shift-A>", self.on_advanced_reverb)  # secret mode

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
    def on_advanced_reverb(self, event: tk.Event | None = None) -> None:
        """
        Secret advanced reverb tuning dialog (Ctrl+Shift+A).

        Lets you tweak:
            - AFIR dry/wet
            - post-volume
            - dry/wet mix
            - limiter on/off
        """
        dialog = tk.Toplevel(self.root)
        dialog.title("Advanced Reverb Tuning")
        dialog.transient(self.root)
        dialog.grab_set()

        frame = ttk.Frame(dialog, padding=10)
        frame.grid(row=0, column=0, sticky="nsew")
        dialog.columnconfigure(0, weight=1)
        dialog.rowconfigure(0, weight=1)

        # Helper to build a row with label + entry
        def add_row(row: int, label: str, var: tk.Variable) -> None:
            ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=2)
            entry = ttk.Entry(frame, textvariable=var, width=10)
            entry.grid(row=row, column=1, sticky="w", padx=(5, 0), pady=2)

        add_row(0, "AFIR dry (0–10):", self.adv_dry)
        add_row(1, "AFIR wet (0–10):", self.adv_wet)
        add_row(2, "Post volume:", self.adv_post_volume)
        add_row(3, "Mix dry weight:", self.adv_mix_dry)
        add_row(4, "Mix wet weight:", self.adv_mix_wet)

        limiter_check = ttk.Checkbutton(
            frame,
            text="Enable soft limiter (alimiter)",
            variable=self.adv_use_limiter,
        )
        limiter_check.grid(row=5, column=0, columnspan=2, sticky="w", pady=(8, 4))

        # Buttons
        btn_frame = ttk.Frame(frame)
        btn_frame.grid(row=6, column=0, columnspan=2, pady=(10, 0), sticky="e")

        def on_ok() -> None:
            # Just close; values are already in the tk.*Var objects
            dialog.destroy()

        def on_reset() -> None:
            # Reset to some sensible defaults
            self.adv_dry.set(4.0)
            self.adv_wet.set(1.0)
            self.adv_post_volume.set(3.0)
            self.adv_mix_dry.set(1.0)
            self.adv_mix_wet.set(1.0)
            self.adv_use_limiter.set(True)

        ttk.Button(btn_frame, text="Reset", command=on_reset).grid(
            row=0, column=0, padx=(0, 5)
        )
        ttk.Button(btn_frame, text="Close", command=on_ok).grid(row=0, column=1)

        dialog.bind("<Escape>", lambda e: dialog.destroy())

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

        # Collect advanced reverb tuning settings
        advanced_reverb = {
            "dry": self.adv_dry.get(),
            "wet": self.adv_wet.get(),
            "post_volume": self.adv_post_volume.get(),
            "mix_dry": self.adv_mix_dry.get(),
            "mix_wet": self.adv_mix_wet.get(),
            "use_limiter": self.adv_use_limiter.get(),
        }

        try:
            export_abc_to_audio(
                abc_path=abc_path,
                out_path=out_path,
                reverb_preset_name=self.reverb_var.get(),
                output_preset_name=output_preset_name,
                soundfont_path=soundfont_path,
                advanced_reverb=advanced_reverb,
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
