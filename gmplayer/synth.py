"""FluidSynth wrapper and MIDI message routing utilities."""
from __future__ import annotations

import threading
from typing import Optional

import fluidsynth
import mido


class FluidSynthWrapper:
    """Manage a FluidSynth instance and translate MIDI messages."""

    def __init__(self, soundfont: str, audio_driver: str | None = None, gain: float = 0.5):
        self.synth = fluidsynth.Synth(gain=gain)
        driver_kwargs = {}
        if audio_driver:
            driver_kwargs["driver"] = audio_driver
        self.synth.start(**driver_kwargs)
        self.sfid = self.synth.sfload(soundfont)
        # Use bank 0 by default
        self.synth.program_select(0, self.sfid, 0, 0)
        self._stop_event = threading.Event()

    def stop(self) -> None:
        """Stop the synthesizer and release resources."""
        self._stop_event.set()
        self.all_notes_off()
        self.synth.delete()

    def all_notes_off(self) -> None:
        """Silence all channels."""
        for channel in range(16):
            self.synth.cc(channel, 123, 0)

    def handle_midi_message(self, msg: mido.Message) -> None:
        """Route a mido message to the synthesizer."""
        if msg.type == "note_on":
            self.synth.noteon(msg.channel, msg.note, msg.velocity)
        elif msg.type == "note_off":
            self.synth.noteoff(msg.channel, msg.note)
        elif msg.type == "control_change":
            self.synth.cc(msg.channel, msg.control, msg.value)
        elif msg.type == "program_change":
            self.synth.program_change(msg.channel, msg.program)
        elif msg.type == "pitchwheel":
            self.synth.pitch_bend(msg.channel, msg.pitch)
        elif msg.type == "aftertouch":
            self.synth.channel_pressure(msg.channel, msg.value)
        elif msg.type == "polytouch":
            self.synth.key_pressure(msg.channel, msg.note, msg.value)
        # Other message types (e.g., sysex, meta) are ignored for the synth.


class MidiInputListener:
    """Listen to a MIDI input port and forward to FluidSynth."""

    def __init__(self, port_name: Optional[str], synth: FluidSynthWrapper):
        self.synth = synth
        self.port_name = port_name
        self.thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()

    def start(self) -> None:
        def _run() -> None:
            with mido.open_input(self.port_name) as port:
                for msg in port:
                    if self._stop_event.is_set():
                        break
                    # Normalize zero-velocity note_on to note_off
                    if msg.type == "note_on" and msg.velocity == 0:
                        msg = msg.copy(type="note_off")
                    self.synth.handle_midi_message(msg)

        self.thread = threading.Thread(target=_run, daemon=True)
        self.thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self.thread:
            self.thread.join(timeout=1)

