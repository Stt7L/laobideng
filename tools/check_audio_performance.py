"""Compare the optimized streaming filter with its original scalar recurrence."""

import math
import os
from pathlib import Path
import sys
import threading
import time

os.environ["OPENBLAS_NUM_THREADS"] = "1"
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from audio_spectrum import AudioSpectrum, fast_bass_energy


def scalar(samples, low, sub, low_alpha, sub_alpha):
    energy = 0.0
    for value in samples:
        low += low_alpha * (float(value) - low)
        sub += sub_alpha * (low - sub)
        filtered = low - sub
        energy += filtered * filtered
    return energy, low, sub


low_alpha = 2 * math.pi * 180 / (48000 + 2 * math.pi * 180)
sub_alpha = 2 * math.pi * 35 / (48000 + 2 * math.pi * 35)
indices = np.arange(1, 1025, dtype=np.float64)
powers = (low_alpha, sub_alpha, (1 - low_alpha) ** indices, (1 - sub_alpha) ** indices)
rng = np.random.default_rng(714)
passed = 0
old_low = old_sub = new_low = new_sub = 0.0
for length in (1, 32, 511, 512, 1024, 2048, 48000, 77):
    samples = rng.normal(0, .15, length).astype(np.float32)
    old = scalar(samples, old_low, old_sub, low_alpha, sub_alpha)
    new = fast_bass_energy(samples, new_low, new_sub, powers, np)
    assert np.allclose(old, new, rtol=1e-10, atol=1e-12), (length, old, new)
    old_low, old_sub = old[1:]
    new_low, new_sub = new[1:]
    passed += 1
for frequency in (35, 60, 180, 1000, 8500):
    samples = np.sin(np.arange(4800) * 2 * np.pi * frequency / 48000).astype(np.float32)
    assert np.allclose(scalar(samples, .1, .05, low_alpha, sub_alpha),
                       fast_bass_energy(samples, .1, .05, powers, np),
                       rtol=1e-10, atol=1e-12)
    passed += 1
samples = rng.normal(0, .15, 2048).astype(np.float32)
durations = []
for method in (lambda: scalar(samples, 0, 0, low_alpha, sub_alpha),
               lambda: fast_bass_energy(samples, 0, 0, powers, np)):
    started = time.perf_counter()
    for _ in range(1000):
        method()
    durations.append((time.perf_counter() - started) * 1000 / 1000)
assert durations[1] < durations[0], durations
meter = AudioSpectrum()
meter._stop = threading.Event()
meter._thread = threading.Thread(target=lambda: time.sleep(.25), daemon=True)
meter._thread.start()
started = time.perf_counter()
meter.close()
assert time.perf_counter() - started < .08, "effect switching waits for recorder cleanup"
meter._thread.join(timeout=1)
assert not meter._thread.is_alive()
passed += 1
print(f"PASS: {passed} filter equivalence checks; scalar={durations[0]:.4f}ms; "
      f"vector={durations[1]:.4f}ms; speedup={durations[0]/durations[1]:.2f}x")
