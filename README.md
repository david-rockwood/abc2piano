# abc2piano

Simple desktop app that converts ABC notation into piano audio.

- Input: .abc file (ABC notation)
- Output: WAV / MP3 / Opus
- Extras: basic reverb presets, realistic piano SoundFont

## Dependencies (development)

- Python 3.11+ (recommended)
- music21
- mido
- pyfluidsynth
- ffmpeg (CLI installed on your system)
- ffmpeg-python (optional, used as a wrapper)

## SoundFont

This app uses the **YDP Grand Piano** soundfont (Yamaha Disklavier Pro),
licensed under **CC-BY 3.0**. The soundfont is **not** stored in the git
repository; it will be provided as a release asset and downloaded or
bundled at build time. See `ATTRIBUTION.md`.

## Release assets (distribution)

To keep the repository small while shipping a portable PyInstaller build, large
runtime dependencies are attached to GitHub releases instead of being tracked
in git. The soundfont is already handled this way. A similar pattern can be
used for the external CLI tools (`abc2midi`, `fluidsynth`, and `ffmpeg`) by
publishing platform-specific archives that are downloaded in CI before running
PyInstaller. See `RELEASE_ASSETS.md` for a proposed layout and size estimates.
