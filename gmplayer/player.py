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
        self._pause_event = threading.Event()
        self._play_thread: threading.Thread | None = None
        self._output_port: Optional[mido.ports.BaseOutput] = None
        self._stream_stats = Counter()
        self._start_time: float | None = None

    @property
    def is_playing(self) -> bool:
        """Return True while the playback thread is active."""
        return self._play_thread is not None and self._play_thread.is_alive()

    def _open_output(self) -> None:
        if self.config.midi_output_port is not None:
            self._output_port = mido.open_output(self.config.midi_output_port)
            logger.info("Sending playback to MIDI output: %s", self.config.midi_output_port)

    def stop(self) -> None:
        """Stop playback and close resources."""
        self._stop_event.set()
        self._pause_event.clear()
        if self._play_thread and self._play_thread.is_alive():
            self._play_thread.join(timeout=1)
        if self._output_port:
            self._output_port.close()
        self._output_port = None

    def pause(self) -> None:
        """Temporarily pause playback."""
        self._pause_event.set()

    def resume(self) -> None:
        """Resume playback after a pause."""
        self._pause_event.clear()

    def _transposed(self, msg: mido.Message) -> mido.Message:
        if msg.type in {"note_on", "note_off", "polytouch"}:
            new_note = max(0, min(127, msg.note + self.config.transpose))
            return msg.copy(note=new_note)
        return msg

    def play(self) -> None:
        """Synchronously play the configured MIDI file (blocking)."""
        self.start()
        if self._play_thread:
            self._play_thread.join()

    def start(self) -> None:
        """Begin playback in a background thread."""
        if self.is_playing:
            self.stop()
        self._stop_event.clear()
        self._pause_event.clear()
        self._stream_stats = Counter()
        self._start_time = None
        self._play_thread = threading.Thread(target=self._play_loop, daemon=True)
        self._play_thread.start()

    def _play_loop(self) -> None:
        self._open_output()
        mid = mido.MidiFile(self.config.midi_file)
        base_tempo = None

        self._log_file_stats(mid)

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

        self._start_time = time.time()
        try:
            for msg in mid:
                if self._stop_event.is_set():
                    break

                while self._pause_event.is_set() and not self._stop_event.is_set():
                    time.sleep(0.05)

                if self._stop_event.is_set():
                    break

                if msg.time:
                    time.sleep(msg.time * tempo_scale)

                if msg.is_meta:
                    continue

                normalized = msg
                if normalized.type == "note_on" and normalized.velocity == 0:
                    normalized = normalized.copy(type="note_off")

                normalized = self._transposed(normalized)
                self.synth.handle_midi_message(normalized)
                if self._output_port:
                    self._output_port.send(normalized)
                self._record_stream_event(normalized)
        finally:
            self._log_stream_stats()
            if self._output_port:
                self._output_port.close()
                self._output_port = None

    def _log_file_stats(self, mid: mido.MidiFile) -> None:
        """Emit statistics about the MIDI file before playback."""
        first_tempo = next((msg.tempo for track in mid.tracks for msg in track if msg.type == "set_tempo"), None)
        base_bpm = round(mido.tempo2bpm(first_tempo)) if first_tempo else 120
        logger.info(
            "MIDI file stats - tracks: %d, ticks_per_beat: %d, length: %.2fs, approx tempo: %sbpm",
            len(mid.tracks),
            mid.ticks_per_beat,
            mid.length,
            base_bpm,
        )

        counter: Counter[str] = Counter()
        for msg in mid:
            if msg.is_meta:
                counter[f"meta:{msg.type}"] += 1
            else:
                counter[msg.type] += 1

        top_events = ", ".join(f"{key}={value}" for key, value in counter.most_common(5))
        logger.info("Top events in file: %s", top_events)

    def _record_stream_event(self, msg: mido.Message) -> None:
        """Track statistics for the outgoing MIDI stream."""
        self._stream_stats[msg.type] += 1
        if msg.type in {"note_on", "note_off"}:
            self._stream_stats["notes"] += 1

    def _log_stream_stats(self) -> None:
        elapsed = time.time() - self._start_time if self._start_time else 0
        if not self._stream_stats:
            logger.info("No MIDI events were sent during playback")
            return

        logger.info(
            "Stream stats - duration: %.2fs, notes: %d, note_on: %d, note_off: %d, total events: %d",
            elapsed,
            self._stream_stats.get("notes", 0),
            self._stream_stats.get("note_on", 0),
            self._stream_stats.get("note_off", 0),
            sum(self._stream_stats.values()),
        )

