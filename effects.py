"""Independent per-key animations.  Coordinates are the photographed keycaps."""

import bisect
import math

from layout import KEYCAPS, LED_CENTERS, NAME_CENTERS


EFFECTS = (
    ("solid", "全键常亮", "均匀、稳定的单色灯光"),
    ("breathe", "柔和呼吸", "整把键盘缓慢明暗起伏"),
    ("rainbow", "双色波浪", "自选两色形成流动光带"),
    ("aurora", "极光渐变", "底色与点缀色缓慢交织"),
    ("meteor", "流星追逐", "一道柔光掠过键盘"),
    ("twinkle", "星光闪烁", "随机键位轻柔闪亮"),
    ("rain", "像素雨", "光点从上往下滴落"),
    ("spiral", "旋转光环", "双色光环围绕中心旋转"),
    ("fire", "柔焰", "自选两色在键盘底部跃动"),
    ("color_cycle", "双色流转", "整把键盘在两色间交替"),
    ("gradient_wave", "渐变潮汐", "两色渐变缓缓经过键盘"),
    ("visor", "往返扫描", "一束光左右来回扫过"),
    ("bubbles", "浮游光点", "柔光在键位之间漂浮"),
    ("mosaic", "流动拼色", "分区色块缓慢更替"),
    ("sunrise", "晨光漫染", "色彩从下向上逐渐蔓延"),
    ("breathing_circle", "呼吸光圈", "同心光圈轻柔扩散"),
    ("cross_beams", "交错光束", "两束柔光交替穿行"),
    ("comet", "彗星掠影", "带有长尾的光点掠过"),
    ("ripple", "暗色涟漪", "常亮底色 · 按键扩散暗环"),
    ("reactive", "按键回响", "每次按键短暂点亮"),
    ("key_bloom", "按键绽放", "触点附近柔光渐次盛开"),
    ("typing_trail", "打字轨迹", "连续按键之间形成光迹"),
    ("key_sweep", "双向扫波", "从按键向左右两侧扫过"),
    ("key_rain", "按键流星", "按键后光点向下坠落"),
    ("heatmap", "敲击余温", "常用键逐渐积累暖光"),
    ("key_cross", "十字闪击", "按键所在行列迅速点亮"),
    ("key_sparks", "键边火花", "按键周围依次迸出细光"),
    ("audio_pulse", "音量脉冲", "整把键盘随播放音量呼吸"),
    ("audio_wave", "节拍光环", "音量跃升时扩散光环"),
    ("audio_ribbon", "声浪丝带", "随音量起伏的流动光带"),
    ("audio_stars", "音乐星群", "音乐越响，光点越繁密"),
    ("audio_meter", "音量刻度", "灯光长度跟随播放音量"),
    ("audio_flash", "重拍闪光", "强音到来时短促闪亮"),
    ("audio_spectrum", "三频跃动", "低频、中频和高频分区起伏"),
    ("audio_ecg", "心电波", "稳定滚动的音乐心电线"),
    ("custom_ecg", "自绘心跳", "点击键位画出图案，让鼓点带它跳动"),
    ("custom_canvas", "逐键画布", "选择键位自由绘制双色图案"),
    ("custom_sparkle", "自绘星图", "让你画出的键位依次闪亮"),
)
EFFECT_IDS = {item[0] for item in EFFECTS}
REACTIVE = {"ripple", "reactive", "key_bloom", "typing_trail", "key_sweep",
            "key_rain", "heatmap", "key_cross", "key_sparks"}
MUSIC = {"audio_pulse", "audio_wave", "audio_ribbon", "audio_stars",
         "audio_meter", "audio_flash", "audio_spectrum", "audio_ecg",
         "custom_ecg"}
CUSTOM = {"custom_ecg", "custom_canvas", "custom_sparkle"}
WIDTH_EFFECTS = {
    "rainbow", "aurora", "meteor", "rain", "spiral", "gradient_wave",
    "visor", "bubbles", "breathing_circle", "cross_beams", "comet",
    "ripple", "reactive", "key_bloom", "typing_trail", "key_sweep",
    "key_rain", "heatmap", "key_cross", "key_sparks",
    "audio_wave", "audio_ribbon", "audio_meter", "audio_spectrum",
    "audio_ecg", "custom_ecg",
}
CATEGORIES = (
    ("regular", "常规灯效", "持续流动与氛围"),
    ("reactive", "互动灯效", "跟随你的每次按键"),
    ("music", "音乐交互", "响应电脑正在播放的声音"),
    ("custom", "自定义灯效", "在键位预览中绘制你的图案"),
)
EFFECT_CATEGORY = {effect_id: ("custom" if effect_id in CUSTOM else
                               "music" if effect_id in MUSIC else
                               "reactive" if effect_id in REACTIVE else "regular")
                   for effect_id in EFFECT_IDS}


def ripple_lifetime(speed):
    """Keep a wave until its outer edge has crossed the longest key span."""
    return 22.0 / (13.0 * max(0.2, speed)) + 0.5


def reactive_lifetime(speed, effect="reactive"):
    duration = {"typing_trail": 1.8, "key_sweep": 1.5, "key_rain": 1.5,
                "heatmap": 2.4, "key_bloom": 1.1, "key_cross": 0.75,
                "key_sparks": 1.2}.get(effect, 0.8)
    return duration / max(0.2, speed)


def mix(a, b, strength):
    strength = max(0.0, min(1.0, strength))
    return tuple(round(a[i] * (1 - strength) + b[i] * strength) for i in range(3))


def scale(color, strength):
    return tuple(round(channel * max(0.0, min(1.0, strength))) for channel in color)


def smoothstep(low, high, value):
    position = max(0.0, min(1.0, (value - low) / (high - low)))
    return position * position * (3 - 2 * position)


def noise(seed):
    return (math.sin(seed * 127.1 + 78.233) * 43758.5453) % 1


def segment_distance(px, py, ax, ay, bx, by):
    dx, dy = bx - ax, by - ay
    length_squared = dx * dx + dy * dy
    if length_squared < 1:
        return math.hypot(px - ax, py - ay)
    fraction = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / length_squared))
    return math.hypot(px - ax - fraction * dx, py - ay - fraction * dy)


def ecg_spike(sample_time, beats):
    """A compact P-QRS-T peak with a quick return to the baseline."""
    value = 0.0
    for started in beats:
        delta = sample_time - started
        if -0.20 < delta < 0.26:
            value += (0.10 * math.exp(-((delta + 0.15) / 0.035) ** 2)
                      - 0.25 * math.exp(-((delta + 0.065) / 0.028) ** 2)
                      + 1.15 * math.exp(-(delta / 0.065) ** 2)
                      - 0.40 * math.exp(-((delta - 0.075) / 0.03) ** 2)
                      + 0.11 * math.exp(-((delta - 0.17) / 0.045) ** 2))
    return max(-0.55, min(1.25, value))


def ecg_trace_at(samples, times, target_time):
    if not samples or target_time < times[0]:
        return 0.0
    index = bisect.bisect_left(times, target_time)
    if index >= len(samples):
        return samples[-1][1]
    if index == 0:
        return samples[0][1]
    previous_time, previous_value = samples[index - 1]
    next_time, next_value = samples[index]
    fraction = (target_time - previous_time) / max(0.001, next_time - previous_time)
    return previous_value + (next_value - previous_value) * fraction


def render(effect, now, base, accent, brightness, speed, events,
           ripple_width=1.0, audio_level=0.0, audio_beats=(),
           audio_impact=0.0, audio_bands=(), audio_trace=(),
           custom_heart_keys=(), custom_canvas_keys=(),
           base_brightness=1.0, accent_brightness=1.0,
           ecg_background=(255, 255, 255)):
    """Return one RGB color per supported LED, indexed by physical LED ID."""
    result = [(0, 0, 0)] * max(105, max(LED_CENTERS, default=0) + 1)
    t = now * max(0.2, speed)
    base_lit = scale(base, brightness * base_brightness)
    accent_lit = scale(accent, brightness * accent_brightness)
    bass, middle, treble = (audio_bands if len(audio_bands) == 3 else
                            (audio_level,) * 3)
    beat_energy = 0.0
    if effect in MUSIC:
        # One response curve for every music effect, including future ones:
        # quieter sustained lows/mids and a short, clearly timed beat accent.
        bass *= 0.70
        middle *= 0.55
        audio_level *= 0.70
        beat_energy = max((math.exp(-(now - started) / 0.18)
                           for started in audio_beats
                           if 0 <= now - started < 0.9), default=0.0)
    ecg_effect = effect in {"audio_ecg", "custom_ecg"}
    trace_times = [sample[0] for sample in audio_trace] if ecg_effect else ()
    heart_beat = (max((math.exp(-(now - started) / 0.32)
                       for started in audio_beats
                       if 0 <= now - started < 1.25), default=0.0)
                  if effect == "custom_ecg" else 0.0)
    painted_caps = ([cap for cap in KEYCAPS if cap.name in custom_heart_keys]
                    if effect == "custom_ecg" else [])
    heart_leds = {led for cap in painted_caps for led in cap.leds}
    # The ECG trace runs behind the user's artwork.  Reserving the selected
    # key area also keeps the line out of intentional gaps inside a shape.
    motif_bounds = ((min(cap.x for cap in painted_caps),
                     min(cap.y for cap in painted_caps),
                     max(cap.x + cap.w for cap in painted_caps),
                     max(cap.y + cap.h for cap in painted_caps))
                    if painted_caps else None)
    canvas_leds = ({led for cap in KEYCAPS
                    if cap.name in custom_canvas_keys
                    for led in cap.leds}
                   if effect in {"custom_canvas", "custom_sparkle"} else set())
    background_lit = scale(ecg_background, brightness) if ecg_effect else None
    width = max(0.5, min(2.0, ripple_width))
    for led, (x, y) in LED_CENTERS.items():
        if effect in REACTIVE or effect == "solid":
            color = base_lit
        elif effect == "breathe":
            level = 0.17 + 0.83 * (0.5 + 0.5 * math.sin(t * 2.2))
            color = scale(mix(base_lit, accent_lit,
                              0.5 + 0.5 * math.sin(t * 0.7)), level)
        elif effect == "rainbow":
            wave = 0.5 + 0.5 * math.sin(x / (90 * width) +
                                        y / (145 * width) - t * 1.2)
            color = mix(base_lit, accent_lit, wave)
        elif effect == "aurora":
            wave = 0.5 + 0.5 * math.sin(x / (82 * width) + t * 1.5 +
                                        math.sin(y / (55 * width) + t))
            color = mix(base_lit, accent_lit, wave)
        elif effect == "meteor":
            head = ((t * 190) % 1000) - 80
            distance = x - head
            glow = (math.exp(-max(0, distance) / (82 * width))
                    if 0 <= distance < 360 * width else 0)
            if -20 * width <= distance < 0:
                glow = 1 - abs(distance) / (20 * width)
            color = mix(scale(base_lit, 0.17), accent_lit, glow)
        elif effect == "twinkle":
            step = int(t * 2.4)
            phase = (t * 2.4) % 1
            pick = noise(led * 71 + step * 13)
            previous = noise(led * 71 + (step - 1) * 13)
            glow = max((1 - phase) * max(0, (pick - 0.87) / 0.13),
                       phase * max(0, (previous - 0.87) / 0.13))
            color = mix(scale(base_lit, 0.22), accent_lit, glow)
        elif effect == "rain":
            column = round(x / 39)
            fall = (t * 2.1 + noise(column * 23) * 5.8) % 7
            row = (y - 53) / 40
            glow = math.exp(-((row - fall) ** 2) / (0.37 * width * width))
            color = mix(scale(base_lit, 0.15), accent_lit, glow)
        elif effect == "spiral":
            dx, dy = (x - 441) / 400, (y - 175) / 150
            angle = math.atan2(dy, dx) / (2 * math.pi)
            radius = math.hypot(dx, dy)
            wave = 0.5 + 0.5 * math.sin((angle + radius * 0.46) *
                                        2 * math.pi / width - t * 1.7)
            color = mix(base_lit, accent_lit, wave)
        elif effect == "fire":
            height = (y - 53) / 245
            flicker = noise(led * 17 + int(t * 8))
            flame = max(0, min(1, height + 0.25 * flicker +
                               0.12 * math.sin(x / 27 + t * 4)))
            color = scale(mix(base_lit, accent_lit, flame), 0.22 + 0.78 * flame)
        elif effect == "color_cycle":
            color = mix(base_lit, accent_lit, 0.5 + 0.5 * math.sin(t * 1.15))
        elif effect == "gradient_wave":
            wave = 0.5 + 0.5 * math.sin(x / (145 * width) -
                                        y / (115 * width) - t * 1.35)
            color = mix(base_lit, accent_lit, wave)
        elif effect == "visor":
            phase = (t * 0.28) % 2
            head = 55 + 760 * (1 - abs(phase - 1))
            glow = math.exp(-((x - head) / (72 * width)) ** 2)
            color = mix(scale(base_lit, 0.32), accent_lit, glow)
        elif effect == "bubbles":
            glow = 0.0
            for bubble in range(4):
                cx = 50 + ((noise(bubble * 11 + 3) * 750 + t * (24 + bubble * 7)) % 820)
                cy = 165 + 95 * math.sin(t * (0.6 + bubble * 0.09) + bubble * 2.2)
                glow = max(glow, math.exp(-((x - cx) / (78 * width)) ** 2 -
                                           ((y - cy) / (65 * width)) ** 2))
            color = mix(scale(base_lit, 0.4), accent_lit, glow)
        elif effect == "mosaic":
            tile = int(x / 78) * 41 + int(y / 53) * 131
            step = int(t * 0.55)
            phase = (t * 0.55) % 1
            blend = (noise(tile + step * 19) * (1 - phase) +
                     noise(tile + (step + 1) * 19) * phase)
            color = mix(base_lit, accent_lit, blend)
        elif effect == "sunrise":
            horizon = 95 + 120 * (0.5 + 0.5 * math.sin(t * 0.8))
            blend = max(0.0, min(1.0, (y - horizon + 95) / 190))
            color = mix(base_lit, accent_lit, blend)
        elif effect == "breathing_circle":
            distance = math.hypot((x - 441) / 110, (y - 175) / 100)
            wave = 0.5 + 0.5 * math.sin(distance * 2.7 / width - t * 1.6)
            color = mix(base_lit, accent_lit, wave)
        elif effect == "cross_beams":
            left = 70 + (t * 90) % 850
            right = 820 - (t * 72) % 850
            glow = max(math.exp(-((x - left) / (58 * width)) ** 2),
                       0.85 * math.exp(-((x - right) / (70 * width)) ** 2))
            color = mix(scale(base_lit, 0.3), accent_lit, glow)
        elif effect == "comet":
            head = (t * 160) % 1100 - 110
            tail = x - head
            glow = math.exp(tail / (105 * width)) if -400 * width < tail <= 0 else 0.0
            glow *= math.exp(-((y - 170 - 55 * math.sin(t * 0.7)) /
                                (100 * width)) ** 2)
            color = mix(scale(base_lit, 0.2), accent_lit, glow)
        elif effect == "audio_pulse":
            pulse = min(1.0, bass * 0.30 + middle * 0.11 +
                        audio_level * 0.12 + audio_impact * 0.55)
            color = mix(scale(base_lit, 0.16), accent_lit, pulse)
        elif effect == "audio_wave":
            distance = math.hypot(x - 441, y - 175)
            # Keep the background movement understated so each kick reads as
            # a distinct travelling ring rather than a constant flicker.
            flow = 0.5 + 0.5 * math.cos(distance / (53 * width) - t * 3.8)
            glow = audio_level * 0.02 + middle * flow * 0.07
            for started in audio_beats:
                age = now - started
                if 0 <= age < 1.5:
                    front = age * 440 * speed
                    ring = math.exp(-((distance - front) / (48 * width)) ** 2)
                    envelope = min(1.0, age / 0.018) * (1 - age / 1.5) ** 0.40
                    glow = max(glow, ring * envelope)
            color = mix(scale(base_lit, 0.18), accent_lit, glow)
        elif effect == "audio_ribbon":
            center = 173 + math.sin(x / 92 - t * 3.0) * (
                13 + bass * 70)
            ribbon = math.exp(-((y - center) / (36 * width)) ** 2)
            shimmer = 0.70 + 0.30 * math.sin(x / 47 + t * 3.5)
            glow = ribbon * shimmer * min(1.0, 0.08 + middle * 0.36 +
                                           treble * 0.18 + audio_impact * 0.38)
            color = mix(scale(base_lit, 0.28), accent_lit, glow)
        elif effect == "audio_stars":
            step = int(t * 2.7)
            phase = (t * 2.7) % 1
            density = 0.07 + treble * 0.40
            pick = noise(led * 31 + step * 17)
            glow = max(0.0, min(1.0, (pick - (1 - density)) / density))
            glow *= math.sin(math.pi * phase) * (0.12 + treble * 0.88)
            color = mix(scale(base_lit, 0.24), accent_lit, glow)
        elif effect == "audio_meter":
            distance = abs(x - 441)
            energy = min(1.0, bass * 0.27 + middle * 0.22 +
                         audio_level * 0.12 + audio_impact * 0.43)
            edge = energy * 400
            fill = smoothstep(distance - 55 * width,
                              distance + 60 * width, edge)
            marker = math.exp(-((distance - edge) / (31 * width)) ** 2) * energy
            color = mix(scale(base_lit, 0.24), accent_lit,
                        min(1.0, fill * 0.78 + marker * 0.22))
        elif effect == "audio_flash":
            glow = max(bass * 0.04, audio_impact * 0.28)
            for started in audio_beats:
                age = now - started
                if 0 <= age < 0.8:
                    flash = (1 - math.exp(-age * 85)) * math.exp(-age * 5.2)
                    glow = max(glow, flash)
            color = mix(scale(base_lit, 0.18), accent_lit, glow)
        elif effect == "audio_spectrum":
            bass_to_mid = smoothstep(320 - 50 * width,
                                     320 + 50 * width, x)
            mid_to_high = smoothstep(610 - 55 * width,
                                     610 + 55 * width, x)
            driven_bass = min(1.0, bass + audio_impact * 0.16)
            band = (driven_bass * (1 - bass_to_mid) + middle * bass_to_mid)
            band = band * (1 - mid_to_high) + treble * mid_to_high
            height = 300 - band * 280
            fill = smoothstep(height - 40 * width,
                              height + 85 * width, y)
            crest = math.exp(-((y - height) / (48 * width)) ** 2) * band
            color = mix(scale(base_lit, 0.18), accent_lit,
                        min(1.0, fill * 0.82 + crest * 0.18))
        elif effect == "custom_canvas":
            color = accent_lit if led in canvas_leds else base_lit
        elif effect == "custom_sparkle":
            if led in canvas_leds:
                step = int(t * 2.1)
                phase = (t * 2.1) % 1
                seed = noise(led * 67 + step * 23)
                glow = max(0.0, (seed - 0.62) / 0.38) * math.sin(math.pi * phase)
                color = mix(base_lit, accent_lit, 0.18 + 0.82 * glow)
            else:
                color = base_lit
        elif ecg_effect:
            # Draw a connected waveform across the whole board.  The segment
            # spans adjacent key columns so a rising note does not turn into
            # isolated specks when the sampled heights differ.
            def wave_height(px):
                sample_time = now - (810 - px) / (420 * max(0.45, speed))
                signal = ecg_trace_at(audio_trace, trace_times, sample_time)
                return 198 - signal * 76 - ecg_spike(
                    sample_time, audio_beats) * 90
            distance = segment_distance(x, y, x - 23, wave_height(x - 23),
                                        x + 23, wave_height(x + 23))
            thickness = 10 + 5 * width
            moving_line = math.exp(-((distance / thickness) ** 2))
            resting_line = 0.19 * math.exp(-(((y - 198) / 20) ** 2))
            line = max(resting_line, moving_line)
            inside_artwork = (motif_bounds is not None and
                              motif_bounds[0] <= x <= motif_bounds[2] and
                              motif_bounds[1] <= y <= motif_bounds[3])
            color = (scale(accent_lit, 0.64 + 0.36 * heart_beat)
                     if led in heart_leds else
                     background_lit if inside_artwork else
                     mix(background_lit, base_lit, line))
        else:
            color = base_lit

        if effect in MUSIC:
            # Keep the ring and heart shapes distinct from the shared beat tint.
            beat_gain = (0.0 if ecg_effect else
                         0.10 if effect == "audio_wave" else 0.28)
            color = mix(color, accent_lit, beat_energy * beat_gain)

        if effect in REACTIVE:
            strongest = 0.0
            for event_index, (name, started) in enumerate(events):
                age = now - started
                lifetime = (ripple_lifetime(speed) if effect == "ripple"
                            else reactive_lifetime(speed, effect))
                if age < 0 or age > lifetime:
                    continue
                origin = NAME_CENTERS.get(name)
                if origin is None:
                    continue
                distance = math.hypot((x - origin[0]) / 39,
                                      (y - origin[1]) / 42)
                if effect == "ripple":
                    # Wireless full frames arrive about 0.13 s apart. Give
                    # each key its own short dark pulse when the wave reaches
                    # it, so the real keyboard cannot skip a thin ring.
                    reached = age - distance / (13.0 * max(0.2, speed))
                    hold = 0.13 * width
                    if reached < 0:
                        strength = 0.0
                    elif reached <= hold:
                        strength = 1.0
                    else:
                        strength = math.exp(-(reached - hold) /
                                            (0.09 * width))
                elif effect == "key_bloom":
                    radius = (28 + age * 130 * speed) * width
                    strength = math.exp(-(distance * 40 / radius) ** 2) * (1 - age / lifetime)
                elif effect == "typing_trail":
                    previous = (NAME_CENTERS.get(events[event_index - 1][0])
                                if event_index else None)
                    line_distance = (segment_distance(x, y, *previous, *origin)
                                     if previous else distance * 39)
                    strength = math.exp(-((line_distance / (37 * width)) ** 2)) * (1 - age / lifetime)
                elif effect == "key_sweep":
                    front = age * 430 * speed
                    strength = (math.exp(-((abs(x - origin[0]) - front) /
                                           (52 * width)) ** 2)
                                * math.exp(-((y - origin[1]) / (75 * width)) ** 2)
                                * (1 - age / lifetime))
                elif effect == "key_rain":
                    fall = origin[1] + age * 255 * speed
                    strength = (math.exp(-((x - origin[0]) / (45 * width)) ** 2
                                         - ((y - fall) / (49 * width)) ** 2)
                                * (1 - age / lifetime))
                elif effect == "heatmap":
                    strength = math.exp(-distance * distance /
                                        (1.4 * width * width)) * (1 - age / lifetime)
                    strongest = min(1.0, strongest + strength * 0.58)
                    continue
                elif effect == "key_cross":
                    strength = (max(math.exp(-((x - origin[0]) / (31 * width)) ** 2),
                                    math.exp(-((y - origin[1]) / (31 * width)) ** 2))
                                * (1 - age / lifetime) ** 2)
                elif effect == "key_sparks":
                    stagger = 0.08 + 0.46 * noise(led * 19 + origin[0] * 0.1)
                    near = math.exp(-(distance / (3.5 * width)) ** 2)
                    strength = (near * math.exp(-((age - stagger) / 0.13) ** 2)
                                * (1 - age / lifetime))
                else:
                    strength = math.exp(-distance * distance /
                                        (0.65 * width * width)) * (1 - age / lifetime)
                strongest = max(strongest, strength)
            color = mix(color, accent_lit, strongest)
        result[led] = color
    return result
