"""Simple Tkinter UI for controlling MIDI playback with FluidSynth."""
from __future__ import annotations

import logging
import pathlib
import threading
from tkinter import Button, DoubleVar, Entry, Frame, Label, StringVar, Tk, filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from .player import MidiFilePlayer, PlaybackConfig
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
        self._lock = threading.Lock()

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
        Entry(controls, textvariable=self.bpm, width=8).grid(row=0, column=1, sticky="w")
        Label(controls, text="Transpose").grid(row=0, column=2, padx=(16, 4))
        ttk.Scale(controls, from_=-24, to=24, variable=self.transpose, orient="horizontal", length=200).grid(
            row=0, column=3, sticky="ew"
        )
        Label(controls, text="(-24 to +24 semitones)").grid(row=0, column=4, sticky="w", padx=(4, 0))

        button_row = Frame(self.root)
        button_row.pack(fill="x", **padding)
        Button(button_row, text="Start", command=self.start).pack(side="left", padx=(0, 6))
        Button(button_row, text="Pause", command=self.pause).pack(side="left", padx=(0, 6))
        Button(button_row, text="Resume", command=self.resume).pack(side="left", padx=(0, 6))
        Button(button_row, text="Stop", command=self.stop).pack(side="left")

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

    def _choose_midi(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("MIDI files", "*.mid *.midi"), ("All files", "*.*")])
        if path:
            self.midi_path.set(path)

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

        with self._lock:
            if self._soundfont_loaded != soundfont:
                self._reset_synth(soundfont)

            if self.player and self.player.is_playing:
                self.player.stop()

            config = PlaybackConfig(midi_file=str(midi_file), bpm=bpm_value, transpose=transpose)
            self.player = MidiFilePlayer(self.synth, config)
            self.player.play()

        self.status.set(f"Playing: {midi_file.name}")

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
