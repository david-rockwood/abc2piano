# abc2piano

Don't run this yet, I'm still setting up the repo. Doesn't work yet.

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
