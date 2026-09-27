"""Physical V98 Pro keycap geometry, traced from the owner's keyboard photo.

Coordinates use the 884 x 343 reference image.  The LED identifiers come from
the published V98 Pro map; several decorative LEDs share wide keycaps.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class Keycap:
    name: str
    label: str
    x: float
    y: float
    w: float = 34
    h: float = 36
    leds: tuple[int, ...] = ()

    @property
    def center(self):
        return (self.x + self.w / 2, self.y + self.h / 2)


KEYCAPS = []


def key(name, label, x, y, w=34, h=36, *leds):
    KEYCAPS.append(Keycap(name, label, x, y, w, h, tuple(leds)))


# Function row and the four navigation keys above the number pad.
key("Esc", "Esc", 57, 53, 36, 36, 0)
for i, x in enumerate((136, 175, 214, 253, 314, 353, 392, 431,
                        491, 530, 569, 608), 1):
    key(f"F{i}", f"F{i}", x, 53, 34, 36, i)
for name, label, x, leds in (("Del", "Del", 670, (13, 78)),
                             ("Insert", "Ins", 709, (14, 79)),
                             ("Page Up", "PgUp", 748, (29, 81)),
                             ("Page Down", "PgDn", 787, (44,))):
    key(name, label, x, 53, 35, 36, *leds)

# Alphanumeric block.  Wide keys and the compact 98% navigation cluster follow
# the supplied photo rather than the coarse 21 x 6 lighting coordinates.
for index, (name, label) in enumerate((("`", "~"), ("1", "1"), ("2", "2"),
                                      ("3", "3"), ("4", "4"), ("5", "5"),
                                      ("6", "6"), ("7", "7"), ("8", "8"),
                                      ("9", "9"), ("0", "0"), ("-_", "−"),
                                      ("=+", "+"))):
    key(name, label, 57 + index * 39, 102, 35, 35, 15 + index)
key("Backspace", "⌫", 568, 102, 76, 35, 28)

key("Tab", "Tab", 57, 142, 51, 35, 30)
for index, letter in enumerate("QWERTYUIOP"):
    key(letter, letter, 115 + index * 39, 142, 35, 35, 31 + index)
for name, label, x, led in (("[", "[", 505, 41), ("]", "]", 544, 42)):
    key(name, label, x, 142, 35, 35, led)
# The backslash key fills the right edge of the row below Backspace.
key("\\", "\\", 583, 142, 61, 35, 43)
key("CapsLock", "Caps", 57, 182, 66, 35, 45)
for index, letter in enumerate("ASDFGHJKL"):
    key(letter, letter, 126 + index * 39, 182, 35, 35, 46 + index)
key(";", ";", 477, 182, 35, 35, 55)
key("'", "'", 516, 182, 35, 35, 56)
key("Enter", "Enter", 556, 182, 88, 35, 57, 58, 59)

key("Left Shift", "⇧ Shift", 57, 222, 82, 35, 60)
for index, letter in enumerate("ZXCVBNM"):
    key(letter, letter, 145 + index * 39, 222, 35, 35, 61 + index)
for name, label, x, led in ((",", ",", 418, 68), (".", ".", 457, 69),
                            ("/", "/", 496, 70)):
    key(name, label, x, 222, 35, 35, led)
key("Right Shift", "⇧ Shift", 536, 222, 67, 35, 71)

key("Left Ctrl", "Ctrl", 57, 262, 47, 35, 75)
key("Left Win", "Win", 108, 262, 47, 35, 76)
key("Left Alt", "Alt", 159, 262, 46, 35, 77)
key("Space", "Space", 209, 262, 237, 35, 80, 82, 83)
key("Fn", "Fn", 450, 262, 47, 35, 84)
key("Right Ctrl", "Ctrl", 501, 262, 47, 35, 85, 86)
key("Left Arrow", "◀", 578, 262, 35, 35, 87)
key("Down Arrow", "▼", 617, 262, 35, 35, 88)
key("Right Arrow", "▶", 656, 262, 35, 35, 89)
key("Up Arrow", "▲", 617, 222, 35, 35, 72)

# Number pad: the + and Enter keys span two rows; zero spans two columns.
for name, label, x, led in (("NumLock", "Num", 670, 90),
                            ("Num /", "/", 709, 91),
                            ("Num *", "×", 748, 92),
                            ("Num -", "−", 787, 93)):
    key(name, label, x, 102, 35, 35, led)
for row, entries in ((142, (("Num 7", "7", 94), ("Num 8", "8", 95),
                                ("Num 9", "9", 96))),
                     (182, (("Num 4", "4", 97), ("Num 5", "5", 98),
                                ("Num 6", "6", 99))),
                     (222, (("Num 1", "1", 73), ("Num 2", "2", 101),
                                ("Num 3", "3", 102)))):
    for index, (name, label, led) in enumerate(entries):
        key(name, label, 670 + index * 39, row, 35, 35, led)
key("Num +", "+", 787, 142, 35, 75, 100)
key("Num Enter", "↵", 787, 222, 35, 75, 74)
key("Num 0", "0", 709, 262, 35, 35, 103)
key("Num .", "Del", 748, 262, 35, 35, 104)


LED_CENTERS = {}
NAME_CENTERS = {}
NAME_LEDS = {}
for cap in KEYCAPS:
    NAME_CENTERS[cap.name] = cap.center
    NAME_LEDS[cap.name] = cap.leds[0]
    for led in cap.leds:
        LED_CENTERS[led] = cap.center

# The wireless map places these under the long spacebar, not beside Enter.
# The three LEDs across the wide Enter key are spaced left to right.
LED_CENTERS.update({57: (575, 200), 58: (603, 200), 59: (628, 200),
                    80: (289, 279),
                    82: (365, 279), 83: (405, 279)})

DEFAULT_KEYCAPS = tuple(KEYCAPS)
DEFAULT_LED_CENTERS = dict(LED_CENTERS)


def set_keycaps(caps):
    """Switch the local preview and reactive geometry without replacing imports."""
    KEYCAPS[:] = caps
    NAME_CENTERS.clear()
    NAME_LEDS.clear()
    LED_CENTERS.clear()
    for cap in caps:
        NAME_CENTERS[cap.name] = cap.center
        if cap.leds:
            NAME_LEDS[cap.name] = cap.leds[0]
        for led in cap.leds:
            LED_CENTERS[led] = cap.center


def restore_v98_layout():
    set_keycaps(DEFAULT_KEYCAPS)
    LED_CENTERS.update(DEFAULT_LED_CENTERS)
