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
    ("digital_rain", "数字雨帘", "错列光点纵向流淌"),
    ("lava_lamp", "熔岩浮岛", "圆润色团缓缓融合漂移"),
    ("diagonal_weave", "斜纹编织", "交错斜纹平稳穿行"),
    ("ripple", "暗色涟漪", "常亮底色 · 按键扩散暗环"),
    ("reactive", "按键回响", "每次按键短暂点亮"),
    ("key_bloom", "按键绽放", "触点附近柔光渐次盛开"),
    ("typing_trail", "打字轨迹", "连续按键之间形成光迹"),
    ("key_sweep", "双向扫波", "从按键向左右两侧扫过"),
    ("key_rain", "按键流星", "按键后光点向下坠落"),
    ("heatmap", "敲击余温", "常用键逐渐积累暖光"),
    ("key_cross", "十字闪击", "按键所在行列迅速点亮"),
    ("key_sparks", "键边火花", "按键周围依次迸出细光"),
    ("key_halo", "触键光晕", "按键外缘浮现一圈柔光"),
    ("key_nexus", "星芒放射", "光束由按键向八方舒展"),
    ("key_echo", "三重回声", "按键接连扩散三道细环"),
    ("key_wipe", "触键擦亮", "颜色从按键向整排推进"),
    ("key_orbit", "环绕微光", "亮点围绕按键短暂旋转"),
    ("key_comet", "横向飞梭", "按键向右掠过一颗彗星"),
    ("key_dust", "星尘散落", "光粒从按键周围散开"),
    ("key_heartbeat", "双击脉冲", "触键亮起两次短促光晕"),
    ("key_checker", "棋盘跃动", "附近键位交替亮起"),
    ("key_row", "整行接力", "亮光沿按键所在行传递"),
    ("key_column", "纵列接力", "亮光沿按键所在列传递"),
    ("key_shadow", "墨迹晕染", "按键附近短暂染成点缀色"),
    ("audio_pulse", "音量脉冲", "整把键盘随播放音量呼吸"),
    ("audio_wave", "节拍光环", "音量跃升时扩散光环"),
    ("audio_ribbon", "声浪丝带", "随音量起伏的流动光带"),
    ("audio_stars", "音乐星群", "音乐越响，光点越繁密"),
    ("audio_meter", "音量刻度", "灯光长度跟随播放音量"),
    ("audio_flash", "重拍闪光", "强音到来时短促闪亮"),
    ("audio_spectrum", "三频跃动", "低频、中频和高频分区起伏"),
    ("audio_ecg", "心电波", "稳定滚动的音乐心电线"),
    ("audio_bassline", "低音地平线", "低频推动底排向上发光"),
    ("audio_ladder", "频谱阶梯", "三频组成交错的亮度台阶"),
    ("audio_dual_meter", "双翼音柱", "两侧光柱随鼓点向中间伸展"),
    ("audio_orbit", "声场轨道", "旋转光点随音量改变轨道"),
    ("audio_kick", "低鼓扩散", "重拍从下缘推开一道光幕"),
    ("audio_snare", "中频琴弦", "中频拉动键盘中央的细线"),
    ("audio_treble", "高音星点", "高频拨亮分散的键位"),
    ("audio_sweep", "节奏游标", "扫描光束随节奏左右行进"),
    ("audio_rain", "声波雨滴", "频段驱动多列下落光点"),
    ("audio_spiral", "旋律漩涡", "音量改变旋转光带的半径"),
    ("audio_diagonal", "斜向鼓浪", "重拍沿斜线掠过键盘"),
    ("audio_mosaic", "音乐透明砖", "频段让不同色块依次明灭"),
    ("audio_beacon", "声源灯塔", "中央柔光随音量收放，强拍聚焦"),
    ("custom_ecg", "自绘心跳", "点击键位画出图案，让鼓点带它跳动"),
    ("custom_canvas", "逐键画布", "选择键位自由绘制双色图案"),
    ("custom_sparkle", "自绘星图", "让你画出的键位依次闪亮"),
)
EFFECT_IDS = {item[0] for item in EFFECTS}
REACTIVE = {"ripple", "reactive", "key_bloom", "typing_trail", "key_sweep",
            "key_rain", "heatmap", "key_cross", "key_sparks", "key_halo",
            "key_nexus", "key_echo", "key_wipe", "key_orbit", "key_comet",
            "key_dust", "key_heartbeat", "key_checker", "key_row",
            "key_column", "key_shadow"}
MUSIC = {"audio_pulse", "audio_wave", "audio_ribbon", "audio_stars",
         "audio_meter", "audio_flash", "audio_spectrum", "audio_ecg",
         "audio_bassline", "audio_ladder", "audio_dual_meter", "audio_orbit",
         "audio_kick", "audio_snare", "audio_treble", "audio_sweep",
         "audio_rain", "audio_spiral", "audio_diagonal", "audio_mosaic",
         "audio_beacon",
         "custom_ecg"}
MOVING_MUSIC = {"audio_orbit", "audio_kick", "audio_sweep", "audio_rain",
                "audio_spiral", "audio_diagonal"}
CUSTOM = {"custom_ecg", "custom_canvas", "custom_sparkle"}
WIDTH_EFFECTS = {
    "rainbow", "aurora", "meteor", "rain", "spiral", "gradient_wave",
    "visor", "bubbles", "breathing_circle", "cross_beams", "comet",
    "ripple", "reactive", "key_bloom", "typing_trail", "key_sweep",
    "key_rain", "heatmap", "key_cross", "key_sparks",
    "audio_wave", "audio_ribbon", "audio_meter", "audio_spectrum",
    "digital_rain", "lava_lamp", "diagonal_weave",
    "key_halo", "key_nexus", "key_echo", "key_wipe", "key_orbit",
    "key_comet", "key_dust", "key_checker", "key_row", "key_column",
    "key_shadow", "audio_bassline", "audio_ladder", "audio_dual_meter",
    "audio_orbit", "audio_kick", "audio_snare", "audio_sweep",
    "audio_rain", "audio_spiral", "audio_diagonal", "audio_mosaic",
    "audio_beacon",
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
                "key_sparks": 1.2, "key_echo": 1.7, "key_wipe": 1.4,
                "key_orbit": 1.3, "key_comet": 1.5, "key_dust": 1.2,
                "key_row": 1.4, "key_column": 1.4, "key_shadow": 1.6,
                "key_heartbeat": 0.9}.get(effect, 0.8)
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
        elif effect == "digital_rain":
            column = round(x / 38)
            head = (t * (77 + 35 * noise(column * 13)) +
                    290 * noise(column * 31)) % 385 - 45
            trail = head - y
            glow = math.exp(-trail / (38 * width)) if 0 <= trail < 185 * width else 0.0
            color = mix(scale(base_lit, 0.15), accent_lit, glow)
        elif effect == "lava_lamp":
            glow = 0.0
            for blob in range(3):
                cx = 200 + 270 * blob + 145 * math.sin(t * (0.37 + blob * 0.1) + blob)
                cy = 165 + 95 * math.sin(t * (0.46 + blob * 0.08) + blob * 2)
                glow += math.exp(-((x - cx) / (140 * width)) ** 2 -
                                 ((y - cy) / (82 * width)) ** 2)
            color = mix(scale(base_lit, 0.35), accent_lit, smoothstep(0.3, 1.4, glow))
        elif effect == "diagonal_weave":
            crossing = math.sin((x + y * 1.8) / (64 * width) - t * 1.4)
            returning = math.sin((x - y * 1.8) / (73 * width) + t * 1.1)
            glow = 0.5 + 0.25 * crossing * returning
            color = mix(base_lit, accent_lit, glow)
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
        elif effect == "audio_bassline":
            crest = 294 - bass * 165 - beat_energy * 53
            glow = smoothstep(crest - 27 * width, crest + 54 * width, y)
            color = mix(scale(base_lit, 0.2), accent_lit, glow * 0.92)
        elif effect == "audio_ladder":
            position = x / 900 * 3
            index = min(2, int(position))
            levels = (bass, middle, treble)
            strength = levels[index] * 0.78 + beat_energy * 0.2
            rung = round(y / (42 * width)) * 42 * width
            glow = math.exp(-((y - rung) / 19) ** 2) * strength
            color = mix(scale(base_lit, 0.2), accent_lit, glow)
        elif effect == "audio_dual_meter":
            energy = min(1.0, bass * 0.55 + middle * 0.18 + beat_energy * 0.55)
            reach = energy * 420
            edge = min(x, 900 - x)
            glow = 1 - smoothstep(reach - 45 * width, reach + 30 * width, edge)
            color = mix(scale(base_lit, 0.18), accent_lit, glow * energy)
        elif effect == "audio_orbit":
            angle = math.atan2(y - 174, x - 440)
            radius = math.hypot((x - 440) / 2.6, y - 174)
            target = 56 + audio_level * 45 + bass * 30
            ring = math.exp(-((radius - target) / (19 * width)) ** 2)
            spot = 0.5 + 0.5 * math.cos(angle - t * 1.9)
            color = mix(scale(base_lit, 0.23), accent_lit,
                        ring * (0.25 + 0.55 * spot + 0.2 * beat_energy))
        elif effect == "audio_kick":
            glow = bass * 0.08
            for started in audio_beats:
                age = now - started
                if 0 <= age < 0.9:
                    front = 300 - age * 370 * speed
                    glow = max(glow, math.exp(-((y - front) / (35 * width)) ** 2)
                               * (1 - age / 0.9))
            color = mix(scale(base_lit, 0.2), accent_lit, glow)
        elif effect == "audio_snare":
            center = 170 + middle * 75 * math.sin(x / 70 - t * 2.5)
            glow = math.exp(-((y - center) / (21 * width)) ** 2)
            color = mix(scale(base_lit, 0.19), accent_lit,
                        glow * min(1.0, middle * 0.8 + audio_impact * 0.4))
        elif effect == "audio_treble":
            phase = t * (1.2 + treble * 3)
            cell = round(x / 38) * 71 + round(y / 39) * 107
            spark = noise(cell + int(phase) * 19)
            glow = max(0.0, (spark - 0.68) / 0.32) * (0.12 + treble * 0.88)
            color = mix(scale(base_lit, 0.2), accent_lit, glow)
        elif effect == "audio_sweep":
            travel = (t * 0.34) % 2
            head = 50 + 780 * (1 - abs(travel - 1))
            glow = math.exp(-((x - head) / (38 * width)) ** 2)
            color = mix(scale(base_lit, 0.2), accent_lit,
                        glow * min(1.0, 0.16 + audio_level * 0.38 + beat_energy * 0.46))
        elif effect == "audio_rain":
            column = round(x / 39)
            band = (bass, middle, treble)[min(2, int(x / 300))]
            fall = (t * (75 + 90 * band) + 250 * noise(column * 29)) % 390 - 45
            glow = math.exp(-((y - fall) / (31 * width)) ** 2)
            color = mix(scale(base_lit, 0.2), accent_lit,
                        glow * min(1.0, band * 0.8 + beat_energy * 0.35))
        elif effect == "audio_spiral":
            angle = math.atan2((y - 175) * 2, x - 440)
            radius = math.hypot((x - 440) / 2, y - 175)
            crest = math.sin(angle * 2 + radius / (29 * width) - t * 2.2)
            glow = smoothstep(0.25, 0.9, crest)
            color = mix(scale(base_lit, 0.2), accent_lit,
                        glow * min(1.0, 0.16 + audio_level * 0.38 + beat_energy * 0.46))
        elif effect == "audio_diagonal":
            coordinate = x + y * 1.7
            glow = 0.0
            for started in audio_beats:
                age = now - started
                if 0 <= age < 1.1:
                    front = age * 1150 * speed
                    glow = max(glow, math.exp(-((coordinate - front) /
                                                (67 * width)) ** 2) * (1 - age / 1.1))
            color = mix(scale(base_lit, 0.2), accent_lit, glow)
        elif effect == "audio_mosaic":
            column = round(x / 54)
            row = round(y / 42)
            band = (bass, middle, treble)[min(2, int(x / 300))]
            pulse = 0.5 + 0.5 * math.sin(t * (1 + band * 3) + column * 1.7 + row)
            glow = pulse * min(1.0, band * 0.68 + beat_energy * 0.42)
            color = mix(scale(base_lit, 0.18), accent_lit, glow)
        elif effect == "audio_beacon":
            radius = (95 + audio_level * 165 + beat_energy * 65) * width
            distance = math.hypot(x - 440, (y - 175) * 2.2)
            glow = math.exp(-((distance / radius) ** 2))
            color = mix(scale(base_lit, 0.2), accent_lit,
                        glow * min(1.0, 0.18 + audio_level * 0.35 +
                                   beat_energy * 0.47))
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
                elif effect == "key_halo":
                    radius = 0.5 + age * 5.2 * speed
                    strength = (math.exp(-((distance - radius) / (0.55 * width)) ** 2)
                                * (1 - age / lifetime))
                elif effect == "key_nexus":
                    angle = math.atan2(y - origin[1], x - origin[0])
                    rays = max(0.0, math.cos(angle * 4) ** 12)
                    front = age * 9.5 * speed
                    strength = rays * math.exp(-((distance - front) /
                                                  (1.4 * width)) ** 2) * (1 - age / lifetime)
                elif effect == "key_echo":
                    strength = 0.0
                    for echo in range(3):
                        progress = age - echo * 0.22 / max(0.2, speed)
                        if progress >= 0:
                            radius = progress * 7.0 * speed
                            strength = max(strength,
                                           math.exp(-((distance - radius) /
                                                      (0.55 * width)) ** 2)
                                           * (1 - age / lifetime) * (1 - echo * 0.2))
                elif effect == "key_wipe":
                    front = age * 570 * speed
                    strength = (1 - smoothstep(front - 45 * width,
                                               front + 45 * width,
                                               abs(x - origin[0])))
                    strength *= (1 - age / lifetime) * 0.8
                elif effect == "key_orbit":
                    angle = age * 11 * speed
                    cx = origin[0] + 88 * width * math.cos(angle)
                    cy = origin[1] + 62 * width * math.sin(angle)
                    strength = (math.exp(-((x - cx) / 44) ** 2 -
                                         ((y - cy) / 44) ** 2)
                                * (1 - age / lifetime))
                elif effect == "key_comet":
                    head = origin[0] + age * 520 * speed
                    tail = head - x
                    strength = (math.exp(-tail / (120 * width))
                                if 0 <= tail < 340 * width else 0.0)
                    strength *= (math.exp(-((y - origin[1]) / (48 * width)) ** 2)
                                 * (1 - age / lifetime))
                elif effect == "key_dust":
                    seed = noise(led * 29 + origin[0] * 0.17)
                    arrival = distance / (8 * speed) + seed * 0.18
                    strength = (math.exp(-((age - arrival) / 0.13) ** 2)
                                * max(0.0, 1 - distance / (9 * width))
                                * (0.4 + seed * 0.6))
                elif effect == "key_heartbeat":
                    flash = max(math.exp(-((age - 0.05) / 0.07) ** 2),
                                0.75 * math.exp(-((age - 0.30) / 0.10) ** 2))
                    strength = math.exp(-(distance / (1.6 * width)) ** 2) * flash
                elif effect == "key_checker":
                    parity = (round(x / 39) + round(y / 42)) % 2
                    switch = int(age * 5 * speed) % 2
                    strength = (math.exp(-(distance / (4.2 * width)) ** 2)
                                * (1 if parity == switch else 0.15)
                                * (1 - age / lifetime))
                elif effect == "key_row":
                    front = age * 500 * speed
                    strength = (math.exp(-((abs(x - origin[0]) - front) /
                                           (38 * width)) ** 2)
                                * math.exp(-((y - origin[1]) / 25) ** 2)
                                * (1 - age / lifetime))
                elif effect == "key_column":
                    front = age * 270 * speed
                    strength = (math.exp(-((abs(y - origin[1]) - front) /
                                           (30 * width)) ** 2)
                                * math.exp(-((x - origin[0]) / 26) ** 2)
                                * (1 - age / lifetime))
                elif effect == "key_shadow":
                    radius = (32 + age * 135 * speed) * width
                    strength = (1 - smoothstep(radius - 35, radius + 18,
                                               math.hypot(x - origin[0], y - origin[1])))
                    strength *= (1 - age / lifetime) * 0.85
                else:
                    strength = math.exp(-distance * distance /
                                        (0.65 * width * width)) * (1 - age / lifetime)
                strongest = max(strongest, strength)
            color = mix(color, accent_lit, strongest)
        result[led] = color
    return result
