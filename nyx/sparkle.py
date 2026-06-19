"""El spinner "sparkle" de Claude Code, como dato puro (sin GTK, testeable).

Frames base reverse-engineered del bundle real (v2.1.183) y expandidos en
palíndromo con endpoints duplicados (· y ✽ laten 2 ticks). 120 ms/frame.
"""

_BASE = ["·", "✢", "✳", "✶", "✻", "✽"]
FRAMES = _BASE + list(reversed(_BASE))  # 12 frames: · ✢ ✳ ✶ ✻ ✽ ✽ ✻ ✶ ✳ ✢ ·
FRAME_MS = 120
PEAK = "✽"  # glifo más lleno (estado estático "talking")
