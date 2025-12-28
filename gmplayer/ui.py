"""Simple Tkinter UI for controlling MIDI playback with FluidSynth."""
from __future__ import annotations

import logging
import pathlib
import threading
from dataclasses import dataclass
from tkinter import Button, DoubleVar, Entry, Frame, Label, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

import mido

from .player import MidiFilePlayer, MidiMetadata, PlaybackConfig, TrackMetadata, extract_midi_metadata
from .synth import FluidSynthWrapper

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class TextHandler(logging.Handler):
    """Redirect log messages into a Tkinter ScrolledText widget."""

    def __init__(self, widget: ScrolledText):
        super().__init__()
        self.widget = widget

    def emit(self, record: logging.LogRecord) -> None:  # pragma: no cover - UI glue
        msg = self.format(record)

        def append() -> None:
            self.widget.configure(state="normal")
            self.widget.insert("end", msg + "\n")
            self.widget.configure(state="disabled")
            self.widget.see("end")

        self.widget.after(0, append)


@dataclass
class TrackUIState:
    index: int
    name: str
    channels: set[int]
    volume_var: DoubleVar
    volume_label: Label
    activity_var: StringVar
    velocity_bar: ttk.Progressbar
    note_label: Label


class PlayerUI:
    def __init__(self) -> None:
        self.root = Tk()
        self.root.title("GM FluidSynth Player")
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self.soundfont_path = StringVar()
        self.midi_path = StringVar()
        self.bpm = StringVar()
        self.transpose = DoubleVar(value=0)
        self.status = StringVar(value="Select a soundfont and MIDI file to begin")

        self.synth: FluidSynthWrapper | None = None
        self.player: MidiFilePlayer | None = None
        self._soundfont_loaded: pathlib.Path | None = None
        self.midi_metadata: MidiMetadata | None = None
        self._midi_metadata_path: pathlib.Path | None = None
        self._lock = threading.Lock()
        self._track_states: dict[int, TrackUIState] = {}
        self._channel_track_map: dict[int, list[int]] = {}
        self._suppress_volume_callback = False

        self._build_layout()

    def _build_layout(self) -> None:
        padding = {"padx": 6, "pady": 6}

        file_frame = Frame(self.root)
        file_frame.pack(fill="x", **padding)

        Label(file_frame, text="SoundFont (SF2)").grid(row=0, column=0, sticky="w")
        Entry(file_frame, textvariable=self.soundfont_path, width=50).grid(row=0, column=1, sticky="ew", padx=4)
        Button(file_frame, text="Browse", command=self._choose_soundfont).grid(row=0, column=2)

        Label(file_frame, text="MIDI File").grid(row=1, column=0, sticky="w")
        Entry(file_frame, textvariable=self.midi_path, width=50).grid(row=1, column=1, sticky="ew", padx=4)
        Button(file_frame, text="Browse", command=self._choose_midi).grid(row=1, column=2)

        controls = Frame(self.root)
        controls.pack(fill="x", **padding)
        controls.columnconfigure(1, weight=1)

        Label(controls, text="Tempo (BPM)").grid(row=0, column=0, sticky="w")
        bpm_entry = Entry(controls, textvariable=self.bpm, width=8)
        bpm_entry.grid(row=0, column=1, sticky="w")
        bpm_entry.bind("<FocusOut>", self._bpm_changed)
        bpm_entry.bind("<Return>", self._bpm_changed)
        Label(controls, text="Transpose").grid(row=0, column=2, padx=(16, 4))
        ttk.Scale(
            controls,
            from_=-24,
            to=24,
            variable=self.transpose,
            orient="horizontal",
            length=200,
            command=lambda _value: self._transpose_changed(),
        ).grid(row=0, column=3, sticky="ew")
        Label(controls, text="(-24 to +24 semitones)").grid(row=0, column=4, sticky="w", padx=(4, 0))

        button_row = Frame(self.root)
        button_row.pack(fill="x", **padding)
        Button(button_row, text="Start", command=self.start).pack(side="left", padx=(0, 6))
        Button(button_row, text="Pause", command=self.pause).pack(side="left", padx=(0, 6))
        Button(button_row, text="Resume", command=self.resume).pack(side="left", padx=(0, 6))
        Button(button_row, text="Stop", command=self.stop).pack(side="left")

        Label(self.root, text="Tracks").pack(fill="x", **padding)
        self.tracks_container = Frame(self.root)
        self.tracks_container.pack(fill="x", **padding)

        Label(self.root, textvariable=self.status).pack(fill="x", **padding)

        self.log_output = ScrolledText(self.root, height=12, state="disabled")
        self.log_output.pack(fill="both", expand=True, **padding)

        handler = TextHandler(self.log_output)
        handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
        logging.getLogger().addHandler(handler)

    def _choose_soundfont(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("SoundFonts", "*.sf2"), ("All files", "*.*")])
        if path:
            self.soundfont_path.set(path)
            self._load_soundfont(pathlib.Path(path))

    def _choose_midi(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")])
        if path:
            self.midi_path.set(path)
            self._load_midi_metadata(pathlib.Path(path))

    def start(self) -> None:
        midi_file = pathlib.Path(self.midi_path.get()).expanduser()
        soundfont = pathlib.Path(self.soundfont_path.get()).expanduser()
        if not midi_file.exists():
            messagebox.showerror("Missing MIDI file", "Please choose a MIDI file to play")
            return
        if not soundfont.exists():
            messagebox.showerror("Missing SoundFont", "Please choose a valid SF2 soundfont")
            return

        try:
            transpose = int(round(self.transpose.get()))
            if transpose < -24 or transpose > 24:
                raise ValueError
        except ValueError:
            messagebox.showerror("Invalid transpose", "Transpose must be between -24 and 24 semitones")
            return

        bpm_raw = self.bpm.get()
        bpm_value = self._parse_bpm(bpm_raw)
        if bpm_raw.strip() and bpm_value is None:
            return

        if self._midi_metadata_path != midi_file:
            self._load_midi_metadata(midi_file)

        with self._lock:
            if self._soundfont_loaded != soundfont:
                self._reset_synth(soundfont)

            if self.player and self.player.is_playing:
                self.player.stop()

            config = PlaybackConfig(midi_file=str(midi_file), bpm=bpm_value, transpose=transpose)
            self.player = MidiFilePlayer(self.synth, config, event_callback=self._handle_midi_event)
            self.player.start()

        self.status.set(f"Playing: {midi_file.name}")

    def _bpm_changed(self, _event=None) -> None:
        bpm_raw = self.bpm.get()
        bpm_value = self._parse_bpm(bpm_raw)
        if bpm_raw.strip() and bpm_value is None:
            return

        with self._lock:
            if self.player:
                self.player.set_bpm(bpm_value)
        if bpm_value:
            self.status.set(f"Tempo set to {bpm_value:.2f} BPM")
        else:
            self.status.set("Tempo reset to file value")

    def _transpose_changed(self) -> None:
        try:
            transpose = int(round(self.transpose.get()))
        except (ValueError, TypeError):
            return

        with self._lock:
            if self.player:
                self.player.set_transpose(transpose)
        self.status.set(f"Transpose set to {transpose:+d} semitones")

    def pause(self) -> None:
        if self.player:
            self.player.pause()
            self.status.set("Paused")

    def resume(self) -> None:
        if self.player:
            self.player.resume()
            self.status.set("Playing")

    def stop(self) -> None:
        with self._lock:
            if self.player:
                self.player.stop()
        self.status.set("Stopped")

    def _on_close(self) -> None:
        self.stop()
        if self.synth:
            self.synth.stop()
        self.root.destroy()

    def _load_midi_metadata(self, midi_path: pathlib.Path) -> None:
        midi_path = midi_path.expanduser()
        try:
            metadata = extract_midi_metadata(str(midi_path))
        except Exception:
            logger.exception("Unable to read MIDI metadata")
            messagebox.showerror("Invalid MIDI file", "Unable to read MIDI metadata from the selected file")
            return

        self.midi_metadata = metadata
        self._midi_metadata_path = midi_path
        self.status.set(f"Loaded MIDI: {midi_path.name} ({len(metadata.tracks)} tracks)")
        self._build_track_controls(metadata)

    def _build_track_controls(self, metadata: MidiMetadata) -> None:
        for child in self.tracks_container.winfo_children():
            child.destroy()
        self._track_states.clear()
        self._channel_track_map = self._map_track_channels(metadata.tracks)

        for track in metadata.tracks:
            state = self._add_track_row(track)
            self._track_states[track.index] = state

        if not metadata.tracks:
            Label(self.tracks_container, text="No track information available").pack(anchor="w")

    def _map_track_channels(self, tracks: list[TrackMetadata]) -> dict[int, list[int]]:
        channel_map: dict[int, list[int]] = {}
        for track in tracks:
            for channel in track.channels:
                channel_map.setdefault(channel, []).append(track.index)
        return channel_map

    def _add_track_row(self, track: TrackMetadata) -> TrackUIState:
        row = Frame(self.tracks_container, relief="groove", borderwidth=1, padx=6, pady=4)
        row.pack(fill="x", pady=2)
        channel_label = ", ".join(str(ch + 1) for ch in sorted(track.channels)) or "n/a"
        Label(row, text=f"{track.name} (ch {channel_label})", width=28, anchor="w").grid(row=0, column=0, sticky="w")

        volume_var = DoubleVar(value=track.volume)
        ttk.Scale(
            row,
            from_=0,
            to=127,
            variable=volume_var,
            orient="horizontal",
            length=180,
            command=lambda value, idx=track.index: self._on_volume_change(idx, value),
        ).grid(row=0, column=1, sticky="ew", padx=(6, 6))

        volume_label = Label(row, text=f"Volume: {int(volume_var.get())}", width=12, anchor="w")
        volume_label.grid(row=0, column=2, sticky="w")

        activity_var = StringVar(value="No notes yet")
        Label(row, textvariable=activity_var, width=22, anchor="w").grid(row=1, column=0, sticky="w", pady=(4, 0))

        velocity_bar = ttk.Progressbar(row, orient="horizontal", length=180, mode="determinate", maximum=127)
        velocity_bar.grid(row=1, column=1, padx=(6, 6), pady=(4, 0), sticky="ew")
        note_label = Label(row, text="Velocity: 0", width=12, anchor="w")
        note_label.grid(row=1, column=2, sticky="w", pady=(4, 0))

        return TrackUIState(
            index=track.index,
            name=track.name,
            channels=track.channels,
            volume_var=volume_var,
            volume_label=volume_label,
            activity_var=activity_var,
            velocity_bar=velocity_bar,
            note_label=note_label,
        )

    def _handle_midi_event(self, msg: mido.Message) -> None:
        """Handle incoming MIDI messages from the player thread and update UI feedback."""

        if msg.type == "note_on" and msg.velocity > 0 and hasattr(msg, "channel"):
            self.root.after(0, lambda: self._update_track_activity(msg.channel, msg.note, msg.velocity))
        elif msg.type == "control_change" and msg.control == 7 and hasattr(msg, "channel"):
            self.root.after(0, lambda: self._sync_channel_volume(msg.channel, msg.value))

    def _sync_channel_volume(self, channel: int, value: int) -> None:
        if self._suppress_volume_callback:
            return

        self._suppress_volume_callback = True
        try:
            for track_index in self._channel_track_map.get(channel, []):
                state = self._track_states.get(track_index)
                if not state:
                    continue
                state.volume_var.set(value)
                self._update_volume_label(state, int(value))
        finally:
            self._suppress_volume_callback = False

    def _update_track_activity(self, channel: int, note: int, velocity: int) -> None:
        for track_index in self._channel_track_map.get(channel, []):
            state = self._track_states.get(track_index)
            if not state:
                continue
            note_name = self._note_name(note)
            state.activity_var.set(f"Note {note_name} (ch {channel + 1})")
            state.velocity_bar["value"] = velocity
            state.note_label.config(text=f"Velocity: {velocity}")
            self.root.after(500, lambda bar=state.velocity_bar: bar.configure(value=0))

    def _on_volume_change(self, track_index: int, raw_value: float | str) -> None:
        if self._suppress_volume_callback:
            return

        try:
            volume_value = int(float(raw_value))
        except (TypeError, ValueError):
            return

        state = self._track_states.get(track_index)
        if not state:
            return
        self._update_volume_label(state, volume_value)

        channels = state.channels
        if not channels:
            return

        for channel in channels:
            msg = mido.Message("control_change", channel=channel, control=7, value=volume_value)
            if self.player:
                self.player.send_immediate(msg)
            elif self.synth:
                self.synth.handle_midi_message(msg)

    def _update_volume_label(self, state: TrackUIState, volume_value: int) -> None:
        state.volume_label.config(text=f"Volume: {volume_value}")

    @staticmethod
    def _note_name(note: int) -> str:
        names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
        octave = (note // 12) - 1
        return f"{names[note % 12]}{octave}"

    def _load_soundfont(self, soundfont: pathlib.Path) -> None:
        soundfont = soundfont.expanduser()
        if not soundfont.exists():
            messagebox.showerror("Missing SoundFont", "Please choose a valid SF2 soundfont")
            return

        with self._lock:
            if self.player and self.player.is_playing:
                self.player.stop()
            self._reset_synth(soundfont)
        self.status.set(f"Loaded soundfont: {soundfont.name}")

    def _reset_synth(self, soundfont: pathlib.Path) -> None:
        if self.synth:
            self.synth.stop()
        self.synth = FluidSynthWrapper(str(soundfont))
        self._soundfont_loaded = soundfont
        logger.info("Loaded soundfont: %s", soundfont)

    @staticmethod
    def _parse_bpm(raw: str) -> float | None:
        raw = raw.strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            messagebox.showerror("Invalid BPM", "Please enter a numeric BPM value")
            return None

    def run(self) -> None:  # pragma: no cover - UI glue
        self.root.mainloop()


def main() -> None:  # pragma: no cover - UI glue
    PlayerUI().run()


if __name__ == "__main__":  # pragma: no cover - UI glue
    main()
