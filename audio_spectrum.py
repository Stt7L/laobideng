"""Analyze the default Windows speaker loopback in memory for music lighting."""

import math
import logging
import threading
import time

import numpy as np
import soundcard as sc

from audio_meter import AudioMeter


SAMPLE_RATE = 48_000
FFT_SIZE = 4096
BANDS = ((35, 180), (180, 2000), (2000, 8500))
FREQUENCIES = np.fft.rfftfreq(FFT_SIZE, 1 / SAMPLE_RATE)
WINDOW = np.hanning(FFT_SIZE).astype(np.float32)
BAND_MASKS = tuple((FREQUENCIES >= low) & (FREQUENCIES < high)
                   for low, high in BANDS)
LOG = logging.getLogger("vgn-ripple.audio")


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
            last_beat = 0.0
            beat_serial = self.beat_serial
            level = 0.0
            impact_envelope = 0.0
            with loopback.recorder(samplerate=SAMPLE_RATE,
                                   blocksize=2048) as recorder:
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
                        stop.wait(0.02)
                        continue
                    mono = np.asarray(data, dtype=np.float32).mean(axis=1)
                    if len(mono) >= FFT_SIZE:
                        samples[:] = mono[-FFT_SIZE:]
                    else:
                        count = len(mono)
                        samples[:-count] = samples[count:]
                        samples[-count:] = mono
                    magnitudes = np.abs(np.fft.rfft(samples * WINDOW)) / (FFT_SIZE / 2)
                    raw_bands = [float(np.sqrt(np.mean(magnitudes[mask] ** 2)))
                                 for mask in BAND_MASKS]
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
                        0.42 if impulse > impact_envelope else 0.12)
                    now = time.perf_counter()
                    if (target_level > 0.12 and impulse > 0.22 and
                            bass > previous_bass * 1.10 and
                            now - last_beat > 0.23):
                        beat_serial += 1
                        last_beat = now
                    bass_average += (bass - bass_average) * (
                        0.065 if bass > bass_average else 0.025)
                    previous_bass = bass
                    with self._lock:
                        self._snapshot = (level, tuple(smoothed), impact_envelope,
                                          beat_serial, last_beat)
                    stop.wait(0.004)
        except Exception as exc:
            if not stop.is_set():
                LOG.warning("Music spectrum unavailable: %s", exc)
                with self._lock:
                    self.error = f"频段分析不可用，已回退到音量模式：{exc}"
                    self.retry_after = time.perf_counter() + 5.0
        finally:
            with self._lock:
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
            self._thread.join(timeout=0.6)
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
