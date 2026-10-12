"""Analyze the default Windows speaker loopback in memory for music lighting."""

import math
import logging
import os
import threading
import time

from audio_meter import AudioMeter


SAMPLE_RATE = 48_000
FFT_SIZE = 2048
BANDS = ((35, 180), (180, 2000), (2000, 8500))
LOG = logging.getLogger("vgn-ripple.audio")


def fast_bass_energy(mono, low, sub, powers, np):
    """Same streaming two-pole filter, evaluated in bounded vector blocks.

    powers are capped at 1024 samples, keeping the exponential recurrence
    numerically stable even when the recorder returns a long audio block.
    """
    low_alpha, sub_alpha, low_powers, sub_powers = powers
    energy = 0.0
    for start in range(0, len(mono), len(low_powers)):
        chunk = np.asarray(mono[start:start + len(low_powers)], dtype=np.float64)
        lp, sp = low_powers[:len(chunk)], sub_powers[:len(chunk)]
        lows = lp * (low + np.cumsum(low_alpha * chunk / lp))
        subs = sp * (sub + np.cumsum(sub_alpha * lows / sp))
        filtered = lows - subs
        energy += float(np.dot(filtered, filtered))
        low, sub = float(lows[-1]), float(subs[-1])
    return energy, low, sub


class AudioSpectrum:
    """Keep loopback recording off the UI thread; fall back to endpoint peaks."""

    def __init__(self):
        self.fallback = AudioMeter()
        self._lock = threading.Lock()
        self._thread = None
        self._stop = None
        self._snapshot = (0.0, (0.0, 0.0, 0.0), 0.0, 0, 0.0)
        self._connected = False
        self.retry_after = 0.0
        self.error = ""
        self.mode = "peak"
        self.level = 0.0
        self.instant = 0.0
        self.average = 0.0
        self.impact = 0.0
        self.rise = 0.0
        self.bands = (0.0, 0.0, 0.0)
        self.beat_serial = 0
        self.beat_time = 0.0

    @property
    def available(self):
        return self._connected or self.fallback.available

    def _start(self):
        if self._thread is not None and self._thread.is_alive():
            return
        stop = threading.Event()
        self._stop = stop
        self._thread = threading.Thread(target=self._capture, args=(stop,),
                                        name="MusicSpectrum", daemon=True)
        self._thread.start()

    def _capture(self, stop):
        try:
            # Neither matrix algebra nor a BLAS thread pool is needed here.
            # Load the analysis stack only when a music effect actually starts,
            # on this worker thread, rather than delaying the window's startup.
            os.environ["OPENBLAS_NUM_THREADS"] = "1"
            import numpy as np
            import soundcard as sc

            if stop.is_set():
                return

            frequencies = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
            window = np.hanning(FFT_SIZE).astype(np.float32)
            band_masks = tuple((frequencies >= low) & (frequencies < high)
                               for low, high in BANDS)
            speaker = sc.default_speaker()
            if speaker is None:
                raise OSError("未找到默认播放设备")
            loopback = sc.get_microphone(speaker.id, include_loopback=True)
            if loopback is None or not loopback.isloopback:
                raise OSError("默认播放设备不支持回环分析")
            samples = np.zeros(FFT_SIZE, dtype=np.float32)
            references = [0.001, 0.001, 0.001]
            smoothed = [0.0, 0.0, 0.0]
            bass_average = 0.0
            previous_bass = 0.0
            fast_low = 0.0
            fast_sub = 0.0
            fast_average = 0.0
            previous_fast = 0.0
            last_fast_beat = 0.0
            beat_pulse = 0.0
            low_alpha = 2 * math.pi * 180 / (SAMPLE_RATE + 2 * math.pi * 180)
            sub_alpha = 2 * math.pi * 35 / (SAMPLE_RATE + 2 * math.pi * 35)
            indices = np.arange(1, 1025, dtype=np.float64)
            filter_powers = (low_alpha, sub_alpha, (1 - low_alpha) ** indices,
                             (1 - sub_alpha) ** indices)
            last_beat = 0.0
            beat_serial = self.beat_serial
            level = 0.0
            impact_envelope = 0.0
            with loopback.recorder(samplerate=SAMPLE_RATE,
                                   blocksize=512) as recorder:
                if stop.is_set():
                    return
                with self._lock:
                    self._connected = True
                    self.error = ""
                LOG.info("Music spectrum connected to %s", speaker.name)
                while not stop.is_set():
                    data = recorder.record(numframes=None)
                    if data is None or data.size == 0:
                        level *= 0.86
                        smoothed = [value * 0.86 for value in smoothed]
                        with self._lock:
                            self._snapshot = (level, tuple(smoothed), 0.0,
                                              beat_serial, last_beat)
                        stop.wait(0.006)
                        continue
                    mono = np.asarray(data, dtype=np.float32).mean(axis=1)
                    # Detect the kick from the newest ~10 ms of audio. Waiting
                    # for the wider FFT window made the visible ring late.
                    fast_energy, fast_low, fast_sub = fast_bass_energy(
                        mono, fast_low, fast_sub, filter_powers, np)
                    fast_bass = math.sqrt(fast_energy / len(mono))
                    fast_impulse = max(0.0, (fast_bass - fast_average) /
                                       max(0.001, fast_average))
                    now = time.perf_counter()
                    beat_pulse *= 0.82
                    if (fast_bass > 0.004 and fast_impulse > 0.20 and
                            fast_bass > previous_fast * 1.08 and
                            now - last_beat > 0.23):
                        beat_serial += 1
                        last_fast_beat = last_beat = now
                        beat_pulse = 1.0
                    fast_average += (fast_bass - fast_average) * (
                        0.07 if fast_bass > fast_average else 0.027)
                    previous_fast = fast_bass
                    if len(mono) >= FFT_SIZE:
                        samples[:] = mono[-FFT_SIZE:]
                    else:
                        count = len(mono)
                        samples[:-count] = samples[count:]
                        samples[-count:] = mono
                    magnitudes = np.abs(np.fft.rfft(samples * window)) / (FFT_SIZE / 2)
                    raw_bands = [float(np.sqrt(np.mean(magnitudes[mask] ** 2)))
                                 for mask in band_masks]
                    for index, raw in enumerate(raw_bands):
                        references[index] = max(raw, references[index] * 0.996)
                        target = min(1.0, raw / max(0.00035, references[index])) ** 1.7
                        smoothed[index] += (target - smoothed[index]) * (
                            0.34 if target > smoothed[index] else 0.11)
                    rms = float(np.sqrt(np.mean(samples ** 2)))
                    target_level = min(1.0, math.sqrt(rms * 7.0))
                    level += (target_level - level) * (
                        0.34 if target_level > level else 0.11)
                    bass = raw_bands[0]
                    impulse = max(0.0, min(1.0,
                        (bass - bass_average) / max(0.0005, bass_average) * 0.85))
                    impact_envelope += (impulse - impact_envelope) * (
                        0.62 if impulse > impact_envelope else 0.15)
                    if (target_level > 0.12 and impulse > 0.22 and
                            bass > previous_bass * 1.10 and
                            now - last_beat > 0.30 and
                            now - last_fast_beat > 0.8):
                        beat_serial += 1
                        last_beat = now
                        beat_pulse = 1.0
                    bass_average += (bass - bass_average) * (
                        0.065 if bass > bass_average else 0.025)
                    previous_bass = bass
                    with self._lock:
                        self._snapshot = (level, tuple(smoothed),
                                          max(impact_envelope * 0.45, beat_pulse),
                                          beat_serial, last_beat)
                    stop.wait(0.002)
        except Exception as exc:
            if not stop.is_set():
                LOG.warning("Music spectrum unavailable: %s", exc)
                with self._lock:
                    self.error = f"频段分析不可用，已回退到音量模式：{exc}"
                    self.retry_after = time.perf_counter() + 5.0
        finally:
            with self._lock:
                if self._stop is stop:
                    self._connected = False

    def sample(self):
        now = time.perf_counter()
        if now >= self.retry_after:
            self._start()
        with self._lock:
            connected = self._connected
            level, bands, impact, serial, beat_time = self._snapshot
        if connected:
            if self.mode != "spectrum":
                self.fallback.close()
            self.mode = "spectrum"
            self.rise = max(0.0, level - self.level)
            self.instant = level
            self.level = level
            self.impact = impact
            self.bands = bands
            self.beat_serial = serial
            self.beat_time = beat_time
        else:
            self.mode = "peak"
            self.level = self.fallback.sample()
            self.instant = self.fallback.instant
            self.average = self.fallback.average
            self.impact = self.fallback.impact
            self.rise = self.fallback.rise
            self.bands = (self.level,) * 3
        return self.level

    def close(self):
        if self._stop is not None:
            self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            # The recorder is owned and released by its worker. Switching an
            # effect must not block the interface for a 600 ms cleanup wait.
            self._thread.join(timeout=0.02)
        self.fallback.close()
        self.mode = "peak"
        self.level = 0.0
        self.instant = 0.0
        self.average = 0.0
        self.impact = 0.0
        self.rise = 0.0
        self.bands = (0.0, 0.0, 0.0)
        with self._lock:
            self._connected = False
            self._snapshot = (0.0, (0.0, 0.0, 0.0), 0.0,
                              self.beat_serial, self.beat_time)

    def refresh(self):
        self.close()
        self.retry_after = 0.0
        self.error = ""
