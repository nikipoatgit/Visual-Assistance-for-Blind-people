"""Offline speech + audio cues.

Every call writes a uniquely named .wav into a temp folder. Unique names matter:
Gradio's Audio component only re-triggers autoplay when the file path changes.
If pyttsx3 is unavailable (no espeak on the machine), speech degrades to a tone
so the app still runs.
"""

import itertools
import os
import tempfile
import wave

import numpy as np

_DIR = os.path.join(tempfile.gettempdir(), "bus_tts")
os.makedirs(_DIR, exist_ok=True)
_counter = itertools.count()
SAMPLE_RATE = 22050


def _path(tag):
    return os.path.join(_DIR, f"{tag}_{next(_counter)}.wav")


def _write_tone(path, beeps, freq=880, dur=0.16, gap=0.08):
    parts = []
    for _ in range(beeps):
        t = np.linspace(0, dur, int(SAMPLE_RATE * dur), endpoint=False)
        envelope = np.minimum(1.0, np.minimum(t, dur - t) * 40)
        parts.append(np.sin(2 * np.pi * freq * t) * envelope * 0.4)
        parts.append(np.zeros(int(SAMPLE_RATE * gap)))
    audio = np.concatenate(parts) if parts else np.zeros(1)
    pcm = (audio * 32767).astype(np.int16)

    with wave.open(path, "wb") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(SAMPLE_RATE)
        f.writeframes(pcm.tobytes())
    return path


def speak(text):
    """Render text to a wav file and return its path (None on total failure)."""
    path = _path("say")
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.setProperty("rate", 165)
        engine.save_to_file(text, path)
        engine.runAndWait()
        engine.stop()
        if os.path.exists(path) and os.path.getsize(path) > 1000:
            return path
    except Exception:
        pass
    return _write_tone(path, beeps=1, freq=660, dur=0.25)


def cue(kind):
    """Short non-speech signals: start, stop, error, success."""
    spec = {
        "start": (1, 990),
        "stop": (2, 520),
        "error": (1, 300),
        "success": (2, 1180),
    }.get(kind, (1, 800))
    beeps, freq = spec
    return _write_tone(_path(kind), beeps=beeps, freq=freq)
