"""MIDI file playback with tempo and transpose controls."""
from __future__ import annotations

import logging
import threading
import time
from collections import Counter

from dataclasses import dataclass
from typing import Optional

import mido

from .synth import FluidSynthWrapper

logger = logging.getLogger(__name__)


@dataclass
class PlaybackConfig:
    midi_file: str
    bpm: Optional[float] = None
    transpose: int = 0
    midi_output_port: Optional[str] = None

    def __post_init__(self) -> None:
        if self.transpose < -24 or self.transpose > 24:
            raise ValueError("transpose must be between -24 and 24 semitones")


class MidiFilePlayer:
    """Play a MIDI file through FluidSynth and optionally mirror to a MIDI output."""

    def __init__(self, synth: FluidSynthWrapper, config: PlaybackConfig):
        self.synth = synth
        self.config = config
        self._stop_event = threading.Event()
        self._output_port: Optional[mido.ports.BaseOutput] = None

    def _open_output(self) -> None:
        if self.config.midi_output_port is not None:
            self._output_port = mido.open_output(self.config.midi_output_port)
            logger.info("Sending playback to MIDI output: %s", self.config.midi_output_port)

    def stop(self) -> None:
        self._stop_event.set()
        if self._output_port:
            self._output_port.close()

    def _transposed(self, msg: mido.Message) -> mido.Message:
        if msg.type in {"note_on", "note_off", "polytouch"}:
            new_note = max(0, min(127, msg.note + self.config.transpose))
            return msg.copy(note=new_note)
        return msg

    def play(self) -> None:
        self._open_output()
        mid = mido.MidiFile(self.config.midi_file)
        base_tempo = None

        for track in mid.tracks:
            for msg in track:
                if msg.type == "set_tempo":
                    base_tempo = msg.tempo
                    break
            if base_tempo:
                break
        if base_tempo is None:
            base_tempo = mido.bpm2tempo(120)

        target_tempo = base_tempo
        if self.config.bpm:
            target_tempo = mido.bpm2tempo(self.config.bpm)
        tempo_scale = target_tempo / base_tempo

        for msg in mid:
            if self._stop_event.is_set():
                break
            if msg.time:
                time.sleep(msg.time * tempo_scale)

            if msg.is_meta:
                continue

            normalized = msg
            if normalized.type == "note_on" and normalized.velocity == 0:
                data = normalized.dict()
                data.pop("type", None)
                normalized = mido.Message("note_off", **data)

            normalized = self._transposed(normalized)
            self.synth.handle_midi_message(normalized)
            if self._output_port:
                self._output_port.send(normalized)

