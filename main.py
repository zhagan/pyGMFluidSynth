"""Command line entry point for the GM FluidSynth MIDI player."""
from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional

from gmplayer.player import MidiFilePlayer, PlaybackConfig
from gmplayer.synth import FluidSynthWrapper, MidiInputListener
from gmplayer.ui import PlayerUI

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Play GM MIDI files using FluidSynth")
    parser.add_argument("--ui", action="store_true", help="Launch the graphical UI instead of the CLI player")
    parser.add_argument("soundfont", nargs="?", help="Path to a General MIDI soundfont (SF2)")
    parser.add_argument("midi_file", nargs="?", help="Path to a MIDI file to play")
    parser.add_argument("--audio-driver", help="FluidSynth audio driver (alsa, pulseaudio, coreaudio, etc.)")
    parser.add_argument("--gain", type=float, default=0.5, help="Output gain for FluidSynth (0.0-1.0)")
    parser.add_argument("--bpm", type=float, help="Override tempo in beats per minute")
    parser.add_argument("--transpose", type=int, default=0, help="Transpose playback in semitones (-24 to 24)")
    parser.add_argument("--midi-input", help="MIDI input port name to feed into FluidSynth")
    parser.add_argument(
        "--midi-output",
        help="MIDI output port name that will receive all events sent to FluidSynth during playback",
    )
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)

    if args.ui:
        PlayerUI().run()
        return 0

    if not args.soundfont or not args.midi_file:
        logger.error("soundfont and midi_file are required when not using --ui")
        return 1
    synth = FluidSynthWrapper(args.soundfont, audio_driver=args.audio_driver, gain=args.gain)
    midi_input_listener = None

    if args.midi_input is not None:
        midi_input_listener = MidiInputListener(args.midi_input, synth)
        midi_input_listener.start()
        logger.info("Listening for MIDI input on: %s", args.midi_input)

    config = PlaybackConfig(
        midi_file=args.midi_file,
        bpm=args.bpm,
        transpose=args.transpose,
        midi_output_port=args.midi_output,
    )
    player = MidiFilePlayer(synth, config)

    try:
        player.play()
    except KeyboardInterrupt:
        logger.info("Playback interrupted by user")
    finally:
        player.stop()
        if midi_input_listener:
            midi_input_listener.stop()
        synth.stop()

    return 0


if __name__ == "__main__":
    sys.exit(main())

