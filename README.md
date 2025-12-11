# abc2piano

A simple desktop app that converts ABC notation into piano audio.

* **Input:** `.abc` file (ABC notation)
* **Output:** WAV / MP3 / Opus
* **Extras:** basic reverb presets, realistic piano SoundFont

## Overview

**abc2piano** is a small wrapper around several excellent free tools. It uses **abc2midi** to convert an ABC notation file into MIDI. Then **FluidSynth** and the **YDP Grand Piano** SoundFont generate a high-quality piano performance from that MIDI. Finally, **FFmpeg** and free convolution reverb impulse responses from *The REAPER Blog* are used to add subtle, natural reverb and optionally compress the result to Opus or MP3.

All of this gives you a simple app you can use to test your ABC files as you write them. You can instantly hear a clean piano rendering of your song without dealing with command-line tools or technical setup. When you're satisfied, just export the audio.

Currently there is only a Linux release, but there is no particular reason it shouldn’t work on other operating systems if you clone the repo and ensure the required dependencies are available in your Python environment.

## Dependencies

You must have the following available in your `PATH` for abc2piano to work:

* `abc2midi`
* `ffmpeg`
* `fluidsynth`
