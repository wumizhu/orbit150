# MicroPython firmware for a DIY Claude Code status light.
#
# Board: Waveshare RP2040-Zero (built-in RGB LED on GP16). Any RP2040 board
# with a WS2812 / NeoPixel LED works; change PIN and NUM_LEDS to match.
#
# The computer sends one word per line over USB serial: green, orange, red or off.
import sys
import time

import machine
import neopixel

PIN = 16                # GP16 = built-in LED on the RP2040-Zero
NUM_LEDS = 1            # raise this if you wire up an LED stick or ring
BRIGHTNESS = 0.4        # 0.0 - 1.0
SWAP_RED_GREEN = False  # set True if "red" shows green (some boards wire the LED in RGB order)

COLORS = {
    "green": (0, 255, 0),
    "orange": (255, 70, 0),
    "red": (255, 0, 0),
    "off": (0, 0, 0),
}

leds = neopixel.NeoPixel(machine.Pin(PIN), NUM_LEDS)


def show(name):
    r, g, b = COLORS[name]
    if SWAP_RED_GREEN:
        r, g = g, r
    color = (int(r * BRIGHTNESS), int(g * BRIGHTNESS), int(b * BRIGHTNESS))
    for i in range(NUM_LEDS):
        leds[i] = color
    leds.write()


# Self-test on power-up so you can see the LED works.
for name in ("red", "orange", "green", "off"):
    show(name)
    time.sleep_ms(400)

while True:
    word = sys.stdin.readline().strip().lower()
    if word in COLORS:
        show(word)
