"""Path B: procedural house — MIDI via mido, audio via a small numpy synth. Instrumental only."""
import os

import mido
import numpy as np
from pydub import AudioSegment

from .spec import NOTE_NAMES, parse_key

SR = 44100
SCALES = {"minor": [0, 2, 3, 5, 7, 8, 10], "major": [0, 2, 4, 5, 7, 9, 11]}


# ---------- music theory ----------

def chord_notes(root_midi: int, mode: str, degree: int) -> list[int]:
    """Diatonic 7th chord on a scale degree."""
    scale = SCALES[mode]
    out = []
    for step in (0, 2, 4, 6):
        idx = degree + step
        out.append(root_midi + scale[idx % 7] + 12 * (idx // 7))
    return out


def arrangement(spec: dict) -> list[dict]:
    """Expand structure into per-bar flags for which parts play."""
    bars = []
    for s in spec["structure"]:
        sec = s["section"]
        for b in range(s["bars"]):
            bars.append({
                "section": sec,
                "kick": sec in ("intro", "drop", "outro") or (sec == "build" and b < s["bars"] - 1),
                "clap": sec in ("drop", "build"),
                "hats": sec != "break",
                "hats16": sec == "drop",
                "bass": sec in ("drop", "build"),
                "chords": True,
                "roll": sec == "build" and b >= s["bars"] - 2,
            })
    return bars


# ---------- MIDI ----------

def build_midi(spec: dict, path: str) -> str:
    root, mode = parse_key(spec["key"])
    root_midi = 48 + NOTE_NAMES.index(root)
    tpb = 480
    mid = mido.MidiFile(ticks_per_beat=tpb)
    tempo = mido.bpm2tempo(spec["bpm"])

    def track(name, channel, events):
        t = mido.MidiTrack()
        t.append(mido.MetaMessage("track_name", name=name))
        t.append(mido.MetaMessage("set_tempo", tempo=tempo))
        msgs = []
        for start, dur, note, vel in events:
            msgs.append((int(start * tpb), mido.Message("note_on", note=note, velocity=vel, channel=channel)))
            msgs.append((int((start + dur) * tpb), mido.Message("note_off", note=note, velocity=0, channel=channel)))
        msgs.sort(key=lambda m: (m[0], m[1].type == "note_on"))
        last = 0
        for tick, msg in msgs:
            t.append(msg.copy(time=tick - last))
            last = tick
        mid.tracks.append(t)

    drums, bass, chords = [], [], []
    prog = spec["chords"]["progression_degrees"]
    bpc = spec["chords"]["bars_per_chord"]
    for i, bar in enumerate(arrangement(spec)):
        b0 = i * 4
        degree = prog[(i // bpc) % len(prog)]
        for beat in range(4):
            if bar["kick"]:
                drums.append((b0 + beat, 0.25, 36, 110))
            if bar["clap"] and beat in (1, 3):
                drums.append((b0 + beat, 0.25, 39, 100))
            if bar["hats"]:
                drums.append((b0 + beat + 0.5, 0.25, 46, 85))
            if bar["bass"]:
                bass.append((b0 + beat + 0.5, 0.4, root_midi - 12 + SCALES[mode][degree], 100))
        if bar["chords"] and i % bpc == 0:
            for n in chord_notes(root_midi + 12, mode, degree):
                chords.append((b0, 4 * bpc - 0.1, n, 70))

    track("drums", 9, drums)
    track("bass", 1, bass)
    track("chords", 2, chords)
    mid.save(path)
    return path


# ---------- synthesis ----------

def _hz(midi: float) -> float:
    return 440.0 * 2 ** ((midi - 69) / 12)


def _kick(n):
    t = np.arange(n) / SR
    freq = 50 + 110 * np.exp(-t * 30)
    return np.sin(2 * np.pi * np.cumsum(freq) / SR) * np.exp(-t * 7)


def _noise_hit(n, decay, hp=True, rng=np.random.default_rng(0)):
    x = rng.standard_normal(n)
    if hp:
        x = np.diff(x, prepend=0)
    return x * np.exp(-np.arange(n) / SR * decay)


def _saw(freq, n, detune=0.0):
    t = np.arange(n) / SR
    out = np.zeros(n)
    for d in (-detune, 0, detune):
        out += 2 * ((t * freq * (1 + d)) % 1) - 1
    return out / 3


def _lowpass(x, alpha):
    y = np.empty_like(x)
    acc = 0.0
    # simple one-pole; vectorised enough for MVP lengths via chunking is unnecessary
    for i in range(len(x)):
        acc += alpha * (x[i] - acc)
        y[i] = acc
    return y


def render(spec: dict, out_path: str) -> str:
    root, mode = parse_key(spec["key"])
    root_midi = 48 + NOTE_NAMES.index(root)
    beat = int(SR * 60 / spec["bpm"])
    bars = arrangement(spec)
    total = len(bars) * 4 * beat + SR
    drums = np.zeros(total)
    bass = np.zeros(total)
    pads = np.zeros(total)
    duck = np.ones(total)

    kick = _kick(beat)
    clap = _noise_hit(int(beat * 0.6), 18)
    ohat = _noise_hit(int(beat * 0.45), 22) * 0.35
    chat = _noise_hit(int(beat * 0.15), 60) * 0.2
    # sidechain envelope: dip to 0.15 on each kick, recover over ~ a beat
    env = 1 - 0.85 * np.exp(-np.arange(beat) / SR * 9)

    prog = spec["chords"]["progression_degrees"]
    bpc = spec["chords"]["bars_per_chord"]

    def add(buf, sig, at):
        end = min(total, at + len(sig))
        buf[at:end] += sig[: end - at]

    for i, bar in enumerate(bars):
        b0 = i * 4 * beat
        degree = prog[(i // bpc) % len(prog)]
        for q in range(4):
            pos = b0 + q * beat
            if bar["kick"]:
                add(drums, kick, pos)
                duck[pos:pos + beat] = np.minimum(duck[pos:pos + beat], env[: len(duck[pos:pos + beat])])
            if bar["clap"] and q in (1, 3):
                add(drums, clap * 0.5, pos)
            if bar["hats"]:
                add(drums, ohat, pos + beat // 2)
            if bar["hats16"]:
                for s in (0, 1, 3):
                    add(drums, chat, pos + s * beat // 4)
            if bar["roll"]:
                for s in range(4):
                    add(drums, clap * 0.25 * (s + 1) / 4, pos + s * beat // 4)
            if bar["bass"]:
                n = int(beat * 0.45)
                note = _saw(_hz(root_midi - 12 + SCALES[mode][degree]), n) * np.exp(-np.arange(n) / SR * 6)
                add(bass, note, pos + beat // 2)
        if i % bpc == 0:
            n = 4 * bpc * beat
            chord = sum(_saw(_hz(m), n, detune=0.004) for m in chord_notes(root_midi + 12, mode, degree))
            fade = np.minimum(1, np.minimum(np.arange(n), n - np.arange(n)) / (SR * 0.05))
            add(pads, chord * fade * 0.12, b0)

    pads = _lowpass(pads, 0.08 if spec["energy"] < 0.6 else 0.15)
    bass = _lowpass(bass, 0.12)
    mix = drums * 0.9 + (bass * 0.6 + pads) * duck
    mix = np.tanh(mix * 1.2)
    mix /= np.max(np.abs(mix)) + 1e-9
    pcm = (mix * 0.9 * 32767).astype(np.int16)
    seg = AudioSegment(pcm.tobytes(), frame_rate=SR, sample_width=2, channels=1)
    try:
        seg.export(out_path, format="mp3", bitrate="192k")
    except Exception as e:  # missing/broken ffmpeg: wav needs no encoder
        print(f"  [audio] mp3 export failed ({type(e).__name__}), writing wav instead")
        if os.path.exists(out_path):
            os.remove(out_path)
        out_path = out_path.rsplit(".", 1)[0] + ".wav"
        seg.export(out_path, format="wav")
    return out_path
