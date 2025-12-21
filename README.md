# pyGMFluidSynth

A minimal Python utility to play General MIDI files using [FluidSynth](https://www.fluidsynth.org/) via the `pyfluidsynth` bindings. It can:

- Load a General MIDI soundfont (SF2) and play MIDI files through FluidSynth.
- Expose a MIDI input port that is routed into FluidSynth for live playing.
- Mirror all events from the MIDI file player to an external MIDI output port.
- Override BPM and transpose playback up/down by up to 24 semitones.

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
python main.py <soundfont.sf2> <song.mid> \
  --audio-driver pulseaudio \
  --bpm 140 \
  --transpose -2 \
  --midi-input "My Keyboard" \
  --midi-output "External Synth"
```

- `soundfont.sf2`: Path to a General MIDI soundfont.
- `song.mid`: Path to the MIDI file to play.
- `--audio-driver`: FluidSynth audio driver (e.g., `alsa`, `pulseaudio`, `coreaudio`).
- `--bpm`: Override the MIDI tempo; if omitted, the file tempo is used.
- `--transpose`: Shift all notes by the given semitones between -24 and 24.
- `--midi-input`: Optional MIDI input port name to feed into FluidSynth.
- `--midi-output`: Optional MIDI output port name that receives all playback events.

Press `Ctrl+C` to stop playback.

## Notes

- Make sure the chosen audio driver is supported by your environment.
- MIDI routing relies on the [`python-rtmidi`](https://pypi.org/project/python-rtmidi/) backend provided by `mido`.

