"""Independent per-key animations.  Coordinates are the photographed keycaps."""

import math

from layout import LED_CENTERS, NAME_CENTERS


EFFECTS = (
    ("ripple", "暗色涟漪", "常亮底色 · 按键扩散暗环"),
    ("solid", "全键常亮", "均匀、稳定的单色灯光"),
    ("breathe", "柔和呼吸", "整把键盘缓慢明暗起伏"),
    ("rainbow", "双色波浪", "自选两色形成流动光带"),
    ("aurora", "极光渐变", "底色与点缀色缓慢交织"),
    ("meteor", "流星追逐", "一道柔光掠过键盘"),
    ("twinkle", "星光闪烁", "随机键位轻柔闪亮"),
    ("rain", "像素雨", "光点从上往下滴落"),
    ("spiral", "旋转光环", "双色光环围绕中心旋转"),
    ("fire", "柔焰", "自选两色在键盘底部跃动"),
    ("reactive", "按键回响", "每次按键短暂点亮"),
    ("color_cycle", "双色流转", "整把键盘在两色间交替"),
    ("gradient_wave", "渐变潮汐", "两色渐变缓缓经过键盘"),
    ("visor", "往返扫描", "一束光左右来回扫过"),
    ("bubbles", "浮游光点", "柔光在键位之间漂浮"),
    ("mosaic", "流动拼色", "分区色块缓慢更替"),
    ("sunrise", "晨光漫染", "色彩从下向上逐渐蔓延"),
    ("breathing_circle", "呼吸光圈", "同心光圈轻柔扩散"),
)
EFFECT_IDS = {item[0] for item in EFFECTS}
REACTIVE = {"ripple", "reactive"}


def ripple_lifetime(speed):
    """Keep a wave until its outer edge has crossed the longest key span."""
    return 22.0 / (13.0 * max(0.2, speed)) + 0.5


def reactive_lifetime(speed):
    return 0.8 / max(0.2, speed)


def mix(a, b, strength):
    strength = max(0.0, min(1.0, strength))
    return tuple(round(a[i] * (1 - strength) + b[i] * strength) for i in range(3))


def scale(color, strength):
    return tuple(round(channel * max(0.0, min(1.0, strength))) for channel in color)


def noise(seed):
    return (math.sin(seed * 127.1 + 78.233) * 43758.5453) % 1


def render(effect, now, base, accent, brightness, speed, events,
           ripple_width=1.0):
    """Return one RGB color per supported LED, indexed by physical LED ID."""
    result = [(0, 0, 0)] * max(105, max(LED_CENTERS, default=0) + 1)
    t = now * max(0.2, speed)
    base_lit = scale(base, brightness)
    accent_lit = scale(accent, brightness)
    for led, (x, y) in LED_CENTERS.items():
        if effect in ("ripple", "solid", "reactive"):
            color = base_lit
        elif effect == "breathe":
            level = 0.17 + 0.83 * (0.5 + 0.5 * math.sin(t * 2.2))
            color = scale(mix(base_lit, accent_lit,
                              0.5 + 0.5 * math.sin(t * 0.7)), level)
        elif effect == "rainbow":
            wave = 0.5 + 0.5 * math.sin(x / 90 + y / 145 - t * 1.2)
            color = mix(base_lit, accent_lit, wave)
        elif effect == "aurora":
            wave = 0.5 + 0.5 * math.sin(x / 82 + t * 1.5 + math.sin(y / 55 + t))
            color = mix(base_lit, accent_lit, wave)
        elif effect == "meteor":
            head = ((t * 190) % 1000) - 80
            distance = x - head
            glow = math.exp(-max(0, distance) / 82) if 0 <= distance < 360 else 0
            if -20 <= distance < 0:
                glow = 1 - abs(distance) / 20
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
            glow = math.exp(-((row - fall) ** 2) / 0.37)
            color = mix(scale(base_lit, 0.15), accent_lit, glow)
        elif effect == "spiral":
            dx, dy = (x - 441) / 400, (y - 175) / 150
            angle = math.atan2(dy, dx) / (2 * math.pi)
            radius = math.hypot(dx, dy)
            wave = 0.5 + 0.5 * math.sin((angle + radius * 0.46) * 2 * math.pi - t * 1.7)
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
            wave = 0.5 + 0.5 * math.sin(x / 145 - y / 115 - t * 1.35)
            color = mix(base_lit, accent_lit, wave)
        elif effect == "visor":
            phase = (t * 0.28) % 2
            head = 55 + 760 * (1 - abs(phase - 1))
            glow = math.exp(-((x - head) / 72) ** 2)
            color = mix(scale(base_lit, 0.32), accent_lit, glow)
        elif effect == "bubbles":
            glow = 0.0
            for bubble in range(4):
                cx = 50 + ((noise(bubble * 11 + 3) * 750 + t * (24 + bubble * 7)) % 820)
                cy = 165 + 95 * math.sin(t * (0.6 + bubble * 0.09) + bubble * 2.2)
                glow = max(glow, math.exp(-((x - cx) / 78) ** 2 -
                                           ((y - cy) / 65) ** 2))
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
            wave = 0.5 + 0.5 * math.sin(distance * 2.7 - t * 1.6)
            color = mix(base_lit, accent_lit, wave)
        else:
            color = base_lit

        if effect in REACTIVE:
            strongest = 0.0
            for name, started in events:
                age = now - started
                lifetime = (ripple_lifetime(speed) if effect == "ripple"
                            else reactive_lifetime(speed))
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
                    hold = 0.13 * ripple_width
                    if reached < 0:
                        strength = 0.0
                    elif reached <= hold:
                        strength = 1.0
                    else:
                        strength = math.exp(-(reached - hold) /
                                            (0.09 * ripple_width))
                else:
                    strength = math.exp(-distance * distance / 0.65) * (1 - age / lifetime)
                strongest = max(strongest, strength)
            color = mix(color, accent_lit, strongest)
        result[led] = color
    return result
