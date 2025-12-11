# abc2piano

Simple desktop app that converts ABC notation into piano audio.

- Input: .abc file (ABC notation)
- Output: WAV / MP3 / Opus
- Extras: basic reverb presets, realistic piano SoundFont

## Dependencies

You must have the following in your PATH for abc2piano to work:

- abc2midi
- ffmpeg
- fluidsynth

## SoundFont

This app uses the **YDP Grand Piano** soundfont (Yamaha Disklavier Pro), licensed under **CC-BY 3.0**. The soundfont is not stored in the git repository; it will be provided as a release asset and bundled at build time. See `ATTRIBUTION.md`.
