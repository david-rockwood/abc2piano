# Release assets for abc2piano

This project keeps large, platform-specific binaries out of the git repository. Instead, the build pipeline downloads them from release assets so the PyInstaller bundle stays reproducible without inflating the repo size. The YDP Grand Piano soundfont is already provided this way. The same pattern can be applied to the external command-line tools the app shells out to.

## Goals

- Keep the git repo source-only while still producing self-contained PyInstaller builds.
- Ship the external tools required at runtime (abc2midi, fluidsynth, ffmpeg) as platform-specific release assets.
- Keep PyInstaller logic simple: unpack the assets into `resources/bin/<platform>/` and point subprocess calls there when frozen.

## Proposed layout

For each supported platform, publish a compressed archive as a release asset that expands to the following structure when downloaded during the build:

```
resources/
  bin/
    linux-x86_64/
      abc2midi
      ffmpeg
      fluidsynth
      libfluidsynth.so* (plus any linked .so dependencies that are not guaranteed to exist on the target distro)
    windows-x86_64/
      abc2midi.exe
      ffmpeg.exe
      fluidsynth.exe
      *.dll (fluidsynth + dependencies)
    macos-universal/
      abc2midi
      ffmpeg
      fluidsynth
      *.dylib (fluidsynth + dependencies)
```

The archives can be named `abc2piano-bin-<platform>.zip` (or `.tar.gz` on Unix) and attached to the GitHub release alongside the soundfont asset.

## Build-time consumption

1. CI downloads the platform-matching archive for the PyInstaller job.
2. The archive is unpacked into `resources/bin/<platform>/` before invoking PyInstaller.
3. The PyInstaller spec uses `--add-binary` (or `Analysis.binaries`) to include that directory. At runtime, the application resolves executable paths under `sys._MEIPASS/resources/bin/<platform>/` instead of relying on the system `PATH`.

This keeps developer installs unchanged: when not frozen, the code can fall back to looking up the tools on `PATH`.

## Asset preparation notes

- **abc2midi:** Statical builds are tiny (<1 MB). Use upstream binaries or a local static build. License is GPL-compatible.
- **fluidsynth:** Bundle its executable plus any non-system shared libraries (e.g., `libfluidsynth`, `glib`, `sndfile`, `readline`). Size varies by platform but typically 3–10 MB once compressed.
- **ffmpeg:** Use a minimal build including the codecs used here (PCM, MP3 via `libmp3lame`, Opus, and `afir` filter support). Static builds compress to ~50–80 MB per platform.
- **Soundfont:** Already shipped as a release asset (~130–150 MB) via `tools/fetch_soundfont.py`.

## CI automation sketch

- Add a build matrix job that prepares the `resources/bin/<platform>/` directory for each OS target by downloading vetted binaries (or building them in CI if necessary) and zipping it as a release asset.
- Reuse these assets in the PyInstaller job: download the matching archive, unpack, and run PyInstaller with the binaries added.
- Keep a checksum manifest (e.g., `tools/release_binaries.json`) to detect drift and make updates explicit.

This approach keeps the repository small while producing fully self-contained PyInstaller bundles for end users.
