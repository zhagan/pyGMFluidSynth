# pyGMFluidSynth

A minimal Python utility to play General MIDI files using [FluidSynth](https://www.fluidsynth.org/) via the `pyfluidsynth` bindings. It can:

- Load a General MIDI soundfont (SF2) and play MIDI files through FluidSynth.
- Expose a MIDI input port that is routed into FluidSynth for live playing.
- Mirror all events from the MIDI file player to an external MIDI output port.
- Override BPM and transpose playback up/down by up to 24 semitones.
- Print quick statistics about the MIDI file and playback stream (duration, events, notes).
- Control playback from a simple UI that supports file selection, BPM override, transpose, and start/pause/stop.


## Requirements

- Python 3.11+
- `fluidsynth` installed on the system (with an audio driver such as ALSA, PulseAudio, or CoreAudio)
- Python dependencies from `requirements.txt`

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Usage

```bash
# CLI playback with logging (including MIDI file and stream statistics)
python main.py <soundfont.sf2> <song.mid> \
  --audio-driver pulseaudio \
  --bpm 140 \
  --transpose -2 \
  --midi-input "My Keyboard" \
  --midi-output "External Synth"

# Launch the Tkinter UI instead of the CLI
python main.py --ui
```

- `soundfont.sf2`: Path to a General MIDI soundfont.
- `song.mid`: Path to the MIDI file to play (omit when using `--ui`).
- `--audio-driver`: FluidSynth audio driver (e.g., `alsa`, `pulseaudio`, `coreaudio`).
- `--bpm`: Override the MIDI tempo; if omitted, the file tempo is used.
- `--transpose`: Shift all notes by the given semitones between -24 and 24.
- `--midi-input`: Optional MIDI input port name to feed into FluidSynth.
- `--midi-output`: Optional MIDI output port name that receives all playback events.

Press `Ctrl+C` to stop playback.

During startup you will see a small summary of the MIDI file (tracks, tempo, and the most
common events). When playback finishes, a stream summary is printed showing the number of
events and notes that were sent along with the elapsed duration.

## Graphical UI

A minimal Tkinter UI is available for loading files and controlling playback.

```bash
python -m gmplayer.ui
```

Within the window you can:

- Browse for an SF2 soundfont and MIDI file.
- Enter a BPM override (leave blank to use the file tempo).
- Drag the transpose slider between -24 and +24 semitones.
- Start, pause/resume, or stop playback.

Log messages (including MIDI statistics) stream into the log panel at the bottom of the UI.

## Notes

- Make sure the chosen audio driver is supported by your environment.
- MIDI routing relies on the [`python-rtmidi`](https://pypi.org/project/python-rtmidi/) backend provided by `mido`.

