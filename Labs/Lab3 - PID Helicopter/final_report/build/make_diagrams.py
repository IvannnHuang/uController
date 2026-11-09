"""Draw the Pico 2 pinout and the system block diagram as SVG, matching imu_demo.c.

Run:  python3 make_diagrams.py      (writes figures/pinout.svg, figures/system_block.svg)
"""
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures")

# Subsystem colours
C = {"vga": "#2563eb", "imu": "#16a34a", "motor": "#ea580c", "dbg": "#6b7280",
     "btn": "#9333ea", "pwr": "#b91c1c"}

# Physical pin -> (silkscreen name, our use or None, subsystem)
LEFT = [  # pins 1..20, top to bottom
    ("GP0", None, None), ("GP1", None, None), ("GND", None, None), ("GP2", None, None),
    ("GP3", None, None), ("GP4", "Motor PWM (slice 2 A) → 4N35 via 330 Ω", "motor"),
    ("GP5", "PWM slice 2 B (level 0, unused)", "dbg"), ("GND", None, None),
    ("GP6", None, None), ("GP7", None, None), ("GP8", "I2C0 SDA → MPU-6050", "imu"),
    ("GP9", "I2C0 SCL → MPU-6050", "imu"), ("GND", "GND → MPU-6050, VGA", "pwr"),
    ("GP10", None, None), ("GP11", None, None), ("GP12", None, None), ("GP13", None, None),
    ("GND", None, None), ("GP14", "ISR timing toggle (scope)", "dbg"),
    ("GP15", "Demo button → GND (pull-up)", "btn"),
]
RIGHT = [  # pins 40..21, top to bottom
    ("VBUS", None, None), ("VSYS", None, None), ("GND", None, None), ("3V3_EN", None, None),
    ("3V3", "3.3 V → MPU-6050 VCC", "pwr"), ("ADC_VREF", None, None), ("GP28", None, None),
    ("GND", None, None), ("GP27", None, None), ("GP26", None, None), ("RUN", None, None),
    ("GP22", None, None), ("GND", None, None), ("GP21", "VGA Red (330 Ω)", "vga"),
    ("GP20", "VGA Blue (330 Ω)", "vga"), ("GP19", "VGA Green hi (330 Ω)", "vga"),
    ("GP18", "VGA Green lo (470 Ω)", "vga"), ("GND", None, None),
    ("GP17", "VGA Vsync", "vga"), ("GP16", "VGA Hsync", "vga"),
]


def pinout():
    W, H = 1000, 640
    bx, by, bw, bh = 400, 40, 200, 560
    pitch = (bh - 40) / 19
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">',
         f'<rect x="{bx}" y="{by}" width="{bw}" height="{bh}" rx="10" fill="#1f6f43" stroke="#0f3d24" stroke-width="2"/>',
         f'<rect x="{bx+80}" y="{by-14}" width="40" height="26" rx="4" fill="#c0c0c0" stroke="#666"/>',
         f'<text x="{bx+100}" y="{by+4}" font-size="10" text-anchor="middle">USB</text>',
         f'<text x="{bx+bw/2}" y="{by+bh/2}" font-size="16" fill="#fff" text-anchor="middle" '
         f'transform="rotate(-90 {bx+bw/2} {by+bh/2})">Raspberry Pi Pico 2 (RP2350)</text>']
    for side, pins in (("L", LEFT), ("R", RIGHT)):
        for i, (name, use, sub) in enumerate(pins):
            y = by + 20 + i * pitch
            num = i + 1 if side == "L" else 40 - i
            px = bx + 10 if side == "L" else bx + bw - 10
            col = C.get(sub, "#d4d4d4") if use else ("#111" if name == "GND" else "#d4d4d4")
            s.append(f'<circle cx="{px}" cy="{y}" r="6" fill="{col}" stroke="#e5e5e5" stroke-width="1.5"/>')
            tx = px + 12 if side == "L" else px - 12
            anchor = "start" if side == "L" else "end"
            s.append(f'<text x="{tx}" y="{y+4}" font-size="11" fill="#fff" text-anchor="{anchor}">{name}</text>')
            nx = bx - 8 if side == "L" else bx + bw + 8
            s.append(f'<text x="{nx}" y="{y+4}" font-size="10" fill="#666" text-anchor="{"end" if side=="L" else "start"}">{num}</text>')
            if use:
                lx0 = bx - 28 if side == "L" else bx + bw + 28
                lx1 = bx - 60 if side == "L" else bx + bw + 60
                s.append(f'<line x1="{lx0}" y1="{y}" x2="{lx1}" y2="{y}" stroke="{C[sub]}" stroke-width="2"/>')
                s.append(f'<text x="{lx1 + (-6 if side=="L" else 6)}" y="{y+4}" font-size="13" font-weight="600" '
                         f'fill="{C[sub]}" text-anchor="{"end" if side=="L" else "start"}">{use}</text>')
    # legend
    ly = H - 18
    items = [("Motor", "motor"), ("IMU / I2C", "imu"), ("VGA", "vga"), ("Button", "btn"), ("Debug / unused", "dbg"), ("Power", "pwr")]
    x = 150
    for label, sub in items:
        s.append(f'<rect x="{x}" y="{ly-10}" width="12" height="12" fill="{C[sub]}"/>')
        s.append(f'<text x="{x+18}" y="{ly}" font-size="12">{label}</text>')
        x += 120
    s.append("</svg>")
    return "\n".join(s)


def box(x, y, w, h, title, sub="", fill="#fff", stroke="#333", bold=False):
    t = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>']
    lines = [title] + ([sub] if isinstance(sub, str) and sub else list(sub) if sub else [])
    n = len(lines)
    for i, ln in enumerate(lines):
        yy = y + h / 2 + (i - (n - 1) / 2) * 15 + 4
        fw = "700" if (i == 0) else "400"
        fs = 13 if i == 0 else 11
        t.append(f'<text x="{x+w/2}" y="{yy}" font-size="{fs}" font-weight="{fw}" text-anchor="middle">{ln}</text>')
    return "\n".join(t)


def arrow(x1, y1, x2, y2, label="", color="#333", lx=None, ly=None, anchor="middle"):
    t = f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" stroke-width="1.6" marker-end="url(#ah)"/>'
    if label:
        lx = (x1 + x2) / 2 if lx is None else lx
        ly = (y1 + y2) / 2 - 6 if ly is None else ly
        t += f'<text x="{lx}" y="{ly}" font-size="11" fill="#444" text-anchor="{anchor}">{label}</text>'
    return t


def system_block():
    W, H = 1000, 560
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" font-family="Helvetica, Arial, sans-serif">',
         '<defs><marker id="ah" markerWidth="10" markerHeight="8" refX="9" refY="4" orient="auto">'
         '<path d="M0,0 L10,4 L0,8 z" fill="#333"/></marker></defs>']
    # RP2350 container
    s.append('<rect x="250" y="20" width="440" height="330" rx="10" fill="#eef4ff" stroke="#2563eb" stroke-width="1.5"/>')
    s.append('<text x="262" y="40" font-size="13" font-weight="700" fill="#2563eb">RP2350 (Pico 2), 150 MHz</text>')
    s.append(box(275, 55, 390, 120, "Core 0: PWM-wrap ISR, exactly 1 kHz",
                 ["read IMU (I2C) → IIR low-pass ax, az → atan2",
                  "complementary filter (0.999 / 0.001)",
                  "button debounce + 0°/+30°/−30°/0° sequence",
                  "PID, conditional integration, clamp 0–6000, slew +20/ms"], fill="#fff"))
    s.append(box(275, 215, 180, 60, "Core 0: serial thread", "a, p, i, d, m, c, n, t", fill="#fff"))
    s.append(box(485, 215, 180, 60, "Core 1: draw thread", "plots + text, every frame", fill="#fff"))
    s.append(box(485, 290, 180, 45, "VGA driver", "3 PIO SMs + DMA chain", fill="#fff"))
    s.append(arrow(365, 215, 365, 177, "volatile globals", lx=372, ly=200, anchor="start"))
    s.append(arrow(575, 177, 575, 213, "angle / duty buffers", lx=582, ly=200, anchor="start"))
    s.append(arrow(575, 275, 575, 288))
    # external
    s.append(box(30, 70, 170, 60, "MPU-6050 IMU", "on the arm, ±2 g, ±250 °/s"))
    s.append(arrow(200, 100, 273, 100, "I2C0 400 kHz"))
    s.append(box(30, 215, 170, 60, "Serial terminal", "laptop (UART / USB)"))
    s.append(arrow(200, 245, 273, 245, "UART"))
    s.append(box(30, 300, 170, 50, "Demo button", "GPIO 15 → GND"))
    s.append('<path d="M 200 325 L 237 325 L 237 160 L 273 160" fill="none" stroke="#333" stroke-width="1.6" marker-end="url(#ah)"/>')
    s.append('<text x="242" y="315" font-size="11" fill="#444">polled in ISR</text>')
    s.append(box(760, 305, 200, 45, "VGA monitor", "640 × 480, 16 colours"))
    s.append(arrow(667, 318, 758, 325, "GPIO 16–21"))
    s.append(box(760, 70, 200, 50, "4N35 optoisolator", "LED side on Pico ground"))
    s.append(arrow(667, 95, 758, 95, "PWM, GPIO 4"))
    s.append(box(760, 150, 200, 50, "IRLB8721 MOSFET", "12 V gate, 1N4001, 0.1 µF"))
    s.append(arrow(860, 120, 860, 148))
    s.append(box(760, 230, 200, 50, "Ducted motor", "5 V supply, thrust ∝ ω²"))
    s.append(arrow(860, 200, 860, 228))
    # physics loop
    s.append(box(380, 440, 240, 60, "Lever arm angle φ", "hinge: torque = thrust − gravity − friction",
                 fill="#fff7ed", stroke="#ea580c"))
    s.append(f'<path d="M 960 255 L 985 255 L 985 470 L 622 470" fill="none" stroke="#ea580c" stroke-width="1.6" marker-end="url(#ah)"/>')
    s.append('<text x="800" y="463" font-size="11" fill="#9a3412">thrust lifts the arm</text>')
    s.append(f'<path d="M 378 470 L 12 470 L 12 100 L 28 100" fill="none" stroke="#ea580c" stroke-width="1.6" marker-end="url(#ah)"/>')
    s.append('<text x="20" y="463" font-size="11" fill="#9a3412">IMU rotates with the arm</text>')
    s.append('<line x1="760" y1="95" x2="760" y2="95"/>')
    s.append('<text x="735" y="540" font-size="11" fill="#666" text-anchor="middle">'
             'Only light crosses the 4N35: the Pico and motor sides have separate supplies and grounds.</text>')
    s.append("</svg>")
    return "\n".join(s)


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    open(os.path.join(OUT, "pinout.svg"), "w").write(pinout())
    open(os.path.join(OUT, "system_block.svg"), "w").write(system_block())
    print("wrote pinout.svg, system_block.svg")
