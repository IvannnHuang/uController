# Lab 2: Digital Galton Board — Design and Optimization Notes

**Target:** Raspberry Pi Pico 2 (RP2350, dual Cortex-M33), 640×480 VGA, 16 colors
**Main file:** [Animation_Demo/animation.c](Animation_Demo/animation.c)
**Final result:** **16,000 balls at 60 fps with ~600 µs of spare time per frame** (350 MHz, both cores)
**Lab requirements added afterwards:** the histogram resets whenever a knob click changes a parameter, an LED lights when a frame misses the 60 fps deadline, and a third knob mode adjusts gravity (see [section 14](#14-lab-requirements-reset-missed-deadline-led-gravity-mode)).

This document records how the code reached that result, step by step: what each change was, why it was made, how it was checked, and what didn't work. It follows the git history from Week 1 to the current version.

**Reading the code:** every optimization is numbered **OPT 1–8**. In `animation.c`, each one has a detailed comment block at its main code (bottleneck, approach, effect, expected vs measured ball count), and the related lines elsewhere carry a short `[OPT n]` tag. [Section 15](#15-optimization-index-opt-tags-in-animationc) maps each tag to the sections below.

---

## Contents
1. [Hardware and interfaces](#1-hardware-and-interfaces)
2. [How a frame works (current architecture)](#2-how-a-frame-works-current-architecture)
3. [Week 1: encoder, ball physics, peg board, sound](#3-week-1-encoder-ball-physics-peg-board-sound)
4. [Week 2: many balls, two cores, faster code](#4-week-2-many-balls-two-cores-faster-code)
5. [Week 3: parallel clear, auto-balance, overclock](#5-week-3-parallel-clear-auto-balance-overclock)
6. [Memory: shrinking the ball from 24 to 12 bytes](#6-memory-shrinking-the-ball-from-24-to-12-bytes)
7. [Hollow pegs and balls](#7-hollow-pegs-and-balls)
8. [Running hot code from SRAM](#8-running-hot-code-from-sram)
9. [Results](#9-results)
10. [Lessons and pitfalls](#10-lessons-and-pitfalls)
11. [Known limitations and harmless races](#11-known-limitations-and-harmless-races)
12. [Ideas for going further](#12-ideas-for-going-further)
13. [Commit and tag map](#13-commit-and-tag-map)
14. [Lab requirements: reset, missed-deadline LED, gravity mode](#14-lab-requirements-reset-missed-deadline-led-gravity-mode)
15. [Optimization index (OPT tags in animation.c)](#15-optimization-index-opt-tags-in-animationc)

---

## 1. Hardware and interfaces

| Signal | GPIO | Notes |
|---|---|---|
| VGA Hsync / Vsync | 16 / 17 | PIO state machines |
| VGA Green lo / hi, Blue, Red | 18 / 19 / 20 / 21 | 4-bit color through resistors |
| Rotary encoder A / B | 12 / 11 | Interrupt on both edges of both pins, internal pull-ups |
| Encoder push button | 10 | Active high, internal pull-down, **polled** (see the E9 erratum below) |
| MCP4822 DAC CS / SCK / MOSI | 13 / 14 / 15 | `spi1`, fed by DMA for the peg sound |
| On-board LED | 25 | Lit when a frame misses the 60 fps deadline (held ~0.5 s) |

**Resources:** PIO0 state machines 0–2 (VGA), DMA channels for VGA plus 2 for sound, and two 153.6 KB frame buffers (307 KB of the 512 KB SRAM).

**Controls:**
- **Knob, BALLS mode:** one click = ±100 balls (1 to `MAX_BALLS`).
- **Knob, BOUNCE mode:** one click = ±0.05 bounciness (0.00 to 1.00).
- **Knob, GRAVITY mode:** one click = ±0.05 gravity (0.05 to 1.00 px/frame², starts at 0.37).
- **Any click that changes a value** resets the histogram and the Fallen count.
- **Button:** steps BALLS → BOUNCE → GRAVITY → BALLS.

**On-screen readout:** Balls, Fallen (since the last reset), Time, Core0 µs, Core1 µs, **Spare µs**, Knob mode, Bounce, Gravity, **Split %**, **Missed** (missed frames since boot).

---

## 2. How a frame works (current architecture)

### 2.1 Frame timing
The VGA driver uses `DOUBLE_BUFFER_60`. At every vsync, a DMA chain does three things with no CPU involvement:
- shows the buffer that was just drawn,
- points `current_draw_buffer` at the other buffer,
- sets `start_flag = 1`, which `draw_start_signal()` reads and clears.

So **both cores together get 16,667 µs to draw each frame.** If they run over, the half-drawn buffer gets displayed anyway (tearing). That's why **Spare** (16,667 − the slower core's time) is the number that sets the ball limit.

### 2.2 Who does what in one frame
```
vsync ─► buffers swap, start_flag = 1 (DMA)

core 0                                      core 1
──────                                      ──────
wait for draw_start_signal()                wait draw_semaphore
if stats_reset: clear histogram + Fallen
SIGNAL draw_semaphore ────────────────────► (wakes)
clear rows 0–239                            clear rows 240–479
poll button, read knob, spawn new balls     drawHistogram()
auto-balance split_pm, compute split
SIGNAL top_semaphore ─────────────────────► WAIT top_semaphore
WAIT bot_semaphore  ◄───────────────────── SIGNAL bot_semaphore
updateAndDrawRange(0, split)                draw 136 hollow pegs
draw text (Balls/Fallen/Core times/…)       updateAndDrawRange(split, num_balls)
core0_us = elapsed                          core1_us = elapsed
WAIT done_semaphore ◄──────────────────── SIGNAL done_semaphore
start_flag already set again? → missed: LED on
```

### 2.3 Who owns which data
| Data | Owner / protection |
|---|---|
| `balls[]` | Split by index: core 0 owns `[0, split)`, core 1 owns `[split, num_balls)`. No ball is touched by both cores in the same frame, so **no lock is needed**. |
| `num_balls`, `split`, spawning new balls | Written only by core 0, and only **before** `top_semaphore` releases core 1 to draw. |
| Histogram counts | `bins_core[2][]` and `fallen_core[2]`: each core writes its own row (`get_core_num()`), and readers add the two rows. `++` isn't atomic across cores, so a shared counter would lose counts. |
| Frame buffer | Both cores draw at once. Balls are always pushed out to `TELEPORT_DIST`, so they never overlap pegs, and the order between cores doesn't matter. |
| Semaphores | `draw` (frame start), `top` / `bot` (two-way barrier after clearing), `done` (core 1 finished). |

---

## 3. Week 1: encoder, ball physics, peg board, sound
*Commits `64a9ac7`, `b6e1fb6`, `dd78e34` (Week 1 checkoff)*

### 3.1 Rotary encoder: `rot_ISR` and `rot_table[16]`
| Change | Purpose |
|---|---|
| Interrupt on **both** edges of **both** A and B | One physical click toggles A twice, so counting only A's edges counted every click twice. |
| 4-state Gray-code lookup table, indexed by `(prev << 2) \| curr` → +1 / −1 / 0 | Every step gets a direction. Illegal jumps (bounce or noise) count as 0. |
| `rot_accum` must reach ±4 **and** the encoder must be back at rest (state 3) to count a click | Contact bounce goes one step forward and one back (+1 −1), so it never reaches ±4. **No debounce timer is needed.** |

### 3.2 One ball and one peg: `updateBall`
The lab's per-frame pseudocode treats a peg as a ball with zero velocity and infinite mass, so a collision reduces to **Δv = −2 (n·v) n**, where n is the unit vector from the peg to the ball.

| Code | Purpose |
|---|---|
| **Substeps:** `steps = speed/4 + 1`, so each frame's motion is split into moves of at most ~4 px | A fast ball can't skip past a peg, or end up deep inside one, between checks. |
| **Bounding box first** (`\|dx\|, \|dy\| < 10`), the exact test only after | Most checks never get to the expensive part. |
| **Teleport** to `TELEPORT_DIST = BALL_RADIUS + PEG_RADIUS + 1` | Moves the ball clear of the peg, so the next substep doesn't detect the same collision again and the ball doesn't stick. |
| **Reflect only if `v·n < 0`** (moving toward the peg) | Reflecting a ball that's already moving away would throw it back into the peg. |
| **`last_peg`:** damping (bounciness) and sound only on a *new* peg | Rolling along one peg doesn't keep losing speed or retriggering the sound. |
| Respawn when the ball leaves the **bottom of the screen** | The demo's old `hitBottom` box crossed through the peg rows and caused a "phantom" second bounce. |

### 3.3 Full board: 16 rows, 136 pegs
| Code | Purpose |
|---|---|
| `initPegs()` fills `peg_x[]` / `peg_y[]` once at startup. Row r has r+1 pegs, rows 19 px apart, pegs 38 px apart. | Peg positions are computed once, not every frame. |
| **`nearestPeg(x, y)`** computes row and column with integer division and returns the one peg the ball could be touching, or −1 | **The key algorithmic change:** each ball checks **1 peg per substep instead of 136**. This works because rows are 19 px apart and the collision distance is only 10 px, so only the nearest peg can be in contact. |

### 3.4 Peg sound through DMA: `initPegSound` / `playPegSound`
| Code | Purpose |
|---|---|
| At startup, build an 800 Hz sine table with a 50-sample linear attack and a linear decay. Each sample already has the DAC's config bits OR'd in. | No math at run time: DMA copies samples straight to SPI. |
| Two chained DMA channels: a **control** channel resets the **data** channel's read address to the start of the table, then triggers it | Each hit plays from the start. **The CPU isn't involved at all.** |
| DMA pacing timer at `clock_get_hz(clk_sys) / 50000` | 50 kHz sample rate, and it adapts automatically when the clock changes (overclocking). |
| `playPegSound()` returns immediately if the DMA is busy | Thousands of hits per second never block or queue up; extra hits are just silent. |
| DAC set to mid-scale (2048) at startup | Avoids a pop on the first sound. |

---

## 4. Week 2: many balls, two cores, faster code
*Commits `0ebb5c7` → `a232bc6` → `89e219a` → `06ecd5e`*

### Step 1: many balls and the histogram (`0ebb5c7`)
- **`ball_t` struct and the `balls[MAX_BALLS]` array** replaced five separate globals. `updateBall(ball_t*)` now works for any ball.
- **The knob sets the ball count.** `target = rot_counter` is read once, because the ISR could change it mid-loop. Raising the count spawns new balls; lowering it just reduces `num_balls`, and the extra balls stop being updated.
- **`binBall()`** counts a ball when its top edge clears the bottom row (`BIN_LINE_Y`). The bin is `(x − BOTTOM_LEFT_X)/38 + 1`, clamped to 0..16. A `binned` flag makes sure each drop counts once.
  - *Why the bottom row and not the bottom of the screen:* balls keep drifting sideways as they fall, so their final position doesn't match the gap they went through.
- **`drawHistogram()`** scales every bar so the tallest is `HIST_H`, which keeps the chart on screen no matter how long it runs.
- The peg sound was shortened from 30 ms to 10 ms, so the DMA is free more often and more hits get heard.

### Step 2: adding core 1 (`a232bc6`), the first big jump
- **Balls split by index:** `split = num_balls × 60%`. Core 0 handles `[0, split)` and core 1 handles the rest. `updateAndDrawBall()` updates one ball and draws it immediately, so the cores never need to sync mid-frame.
- **A histogram per core** (`bins_core[2][]`, `fallen_core[2]`) removes the `++` race between cores.
- **`done_semaphore`** was added next to `draw_semaphore`, forming a fork/join barrier. Without it, core 0 could clear the next frame while core 1 was still drawing, and balls flickered.
- **Pegs moved to core 1**, which is why core 0 started with 60% of the balls.
- **On-screen Core0 / Core1 / Spare µs**, so the limit can be measured instead of guessed.
- Side-wall bounces were removed (as on a real board), balls spawn at `BOARD_TOP_Y − 50`, and bounciness went from 0.5 to 0.3.

### Step 3: button mode and the fast ball sprite (`89e219a`, 5,000 balls)
- **`rot_click(dir)`** handles knob clicks for both modes and clamps the values. `bounciness` became a `volatile fix15` so it can change at run time.
- **`pollButton()`** reads the button once per frame. At ~16 ms per frame, that's slower than contact bounce, so each press is seen exactly once.
  - **RP2350 erratum E9:** a pin with the internal pull-down enabled can latch at ~2 V and keep reading 1 after the button is released. Fix: keep the pin's input buffer **off**, and turn it on only for the 1 µs sample.
- **`drawBall` + `drawSpan`**, the biggest drawing speedup:
  - The problem: `fillCircle` recomputes 5 software square roots and makes 10 `drawHLine` calls for every ball, every frame.
  - The fix: compute the row half-widths once (`ball_dx[]`) and write bytes straight into `current_draw_buffer` (2 pixels per byte).
  - Balls touching the screen edge still use the library call, which handles clipping.
- **`32768.0f` instead of `32768.0`:** the M33 FPU is single-precision only, so a `double` constant forces slow software math.
- Collision normal: one `divfix(1, distance)` and two multiplies, instead of two `divfix` calls.

### Step 4: faster collision math (`06ecd5e`, 5,200 balls)
- **Fast path below the board:** once `y > BIN_LINE_Y`, there are no pegs left, so the ball just does `x += vx; y += vy`. That's about half the balls on screen.
- **`step_vx = vx / steps` computed once** before the substep loop, instead of dividing on every substep.
- **Compare squared distances** (`dist2 < COLLIDE_DIST2`), so near-misses never take a square root.
- **`1.0f / sqrtf(...)` on the FPU** for the normal, replacing the 64-bit software `divfix`.

---

## 5. Week 3: parallel clear, auto-balance, overclock
*Commits `9de77d0`, `d0a9659`*

### 5.1 Clearing the screen on both cores
**Before:** core 0 cleared the whole 153.6 KB buffer and drew the histogram while core 1 sat idle. That time also didn't appear in `core1_us`, so Spare looked better than it really was.

**After:**
- Core 0 wakes core 1 the moment vsync arrives. Core 0 clears rows 0–239 and core 1 clears rows 240–479 (`CLEAR_SPLIT_Y`).
- Core 1 then draws the histogram, which sits entirely in the bottom half. Core 0 isn't counting balls into the histogram at that point, so the counts are stable.
- **`top_semaphore` / `bot_semaphore` form a two-way barrier.** No core may draw until both halves are clear, because any ball can be anywhere on screen.
- The knob and spawn work still happens before core 1 is released, so core 1 always sees the final `num_balls` and `split`.

### 5.2 Automatic split balancing
```c
int diff = (int)core1_us - (int)core0_us ;          // last frame's finish times
if      (diff >  SPLIT_DEADBAND) split_pm = MIN(split_pm + 1, 1000) ;
else if (diff < -SPLIT_DEADBAND) split_pm = MAX(split_pm - 1, 0) ;
split = (num_balls * split_pm) / 1000 ;
```
- **Why it's needed:** the cost per ball depends on where the balls are. Balls in the peg area use substeps; falling balls don't. A fixed 60% is never quite right.
- **Why it doesn't oscillate:** there's a 50 µs deadband, and the share moves only 0.1% per frame (about 6% per second).
- **Why per-mille:** the share scales automatically when the knob changes the ball count.
- **Why both times start at vsync:** they include barrier waits, so the controller balances *finish times*, which is what matters.
- `Split: xx.x%` is shown on screen.

### 5.3 Overclocking: the rule
VGA needs a fixed **25 MHz pixel clock**. The driver gets it two ways:
- **Sync signals:** `hsync.pio` and `vsync.pio` run their state machines at `clkdiv = D`.
- **Pixel output:** `rgb.pio` runs at the full system clock. Each loop outputs 2 pixels:
  - first pixel: `out [pixel1hold]` = 1 + a cycles
  - second pixel: `out [pixel2hold]` + `jmp` + `pull` = (1 + b) + 2 cycles

**For sys_clk = D × 25 MHz: sync `clkdiv = D`, `pixel1hold = D − 1`, `pixel2hold = D − 3`.**

| sys_clk | D | clkdiv | pixel1hold / pixel2hold |
|---|---|---|---|
| 150 MHz (stock) | 6 | 6 | 5 / 3 |
| 300 MHz | 12 | 12 | 11 / 9 |
| **350 MHz (current)** | **14** | **14** | **13 / 11** |

Things that **don't** need changing:
- the DMA sound timer (it reads `clock_get_hz(clk_sys)` at startup),
- SPI, UART and `time_us_*`,
- `FRAME_BUDGET_US` (the display is still 60 Hz).

### 5.4 300 MHz (`9de77d0`)
- `vreg_set_voltage(VREG_VOLTAGE_1_30)` first, a 10 ms wait, then `set_sys_clock_khz(300000, true)`.
- **The RP2350 does not raise its core voltage automatically** (the SDK only does this for the RP2040 at 200 MHz), and the default 1.10 V isn't enough. 1.30 V is the highest setting available without unlocking the regulator.

### 5.5 350 MHz (`d0a9659`): the PLL trap
- **The SDK can't make 350 MHz.** `set_sys_clock_khz()` only searches with reference divider 1, so the PLL's VCO must be a multiple of the 12 MHz crystal. 350 MHz needs a 1050 MHz VCO (÷3 ÷1), and 1050/12 = 87.5 isn't an integer. `set_sys_clock_khz(350000, true)` would **halt the board at boot.**
  - This is why an earlier uncommitted attempt used 340 MHz (1020/12 = 85 works). But 340 MHz with D = 14 gives a 24.29 MHz pixel clock and **57.9 Hz** frames, which some monitors reject.
- **The fix:** program the PLL directly, with the same steps as the SDK's `set_sys_clock_pll()` but **reference divider 2**: 6 MHz × 175 = 1050 MHz, ÷3 = exactly 350 MHz.
  ```c
  clock_configure_undivided(clk_sys, ...AUX, ...PLL_USB, USB_CLK_HZ) ;   // park clk_sys on 48 MHz
  pll_init(pll_sys, 2, 1050 * MHZ, 3, 1) ;                              // refdiv 2
  clock_configure_undivided(clk_sys, ...AUX, ...PLL_SYS, 350 * MHZ) ;
  clock_configure_undivided(clk_peri, 0, ...PLL_USB, USB_CLK_HZ) ;      // UART/SPI stay on 48 MHz
  ```
  - These values pass all of `pll_init`'s checks: VCO in the 750–1600 MHz range, FBDIV = 175 (16..320), 6 MHz reference ≥ the RP2350's 5 MHz minimum.
  - Changing `PLL_SYS_REFDIV` globally was rejected, because the SDK's built-in 150 MHz boot preset requires refdiv 1.
  - `clock_configure_undivided` records the frequency, so `clock_get_hz(clk_sys)` returns 350 MHz and the sound timer still works.

### 5.6 Flash clock note
`CMakeLists.txt` builds a custom boot stage 2 with `PICO_FLASH_SPI_CLKDIV=4`. On the RP2350 the SDK only embeds that stage when `PICO_EMBED_XIP_SETUP=1` (default 0), so it **probably has no effect**. The board runs fine at 350 MHz as-is. If an overclock ever hangs at boot, adding
`target_compile_definitions(VGA_Animation_Demo PRIVATE PICO_EMBED_XIP_SETUP=1)` is the first thing to try. Section 8 also moves the hot code out of flash.

---

## 6. Memory: shrinking the ball from 24 to 12 bytes
After the overclock, **RAM became the limit rather than the CPU.** The two frame buffers take 307 KB of the 512 KB SRAM, and raising `MAX_BALLS` past ~8,000 at 24 bytes per ball caused a **linker overflow**.

### 6.1 The progression
| Version | Layout | Bytes | `MAX_BALLS` | Outcome |
|---|---|---|---|---|
| Original | `fix15 x, y, vx, vy; int last_peg; int binned` | 24 | 8,000 | linker overflow above ~8k |
| `64bb7eb` | `last_peg` → `int16_t`, `binned` → `uint8_t` | 20 | 10,000 | ✅ |
| *(attempt, reverted)* | `vx, vy` as `int16_t` with 8 fractional bits | 16 | 12,500 | ❌ **histogram wrong** |
| `b3d6a87` | `x, y, vy` fix15 + `vx_meta` = vx (23 bits) \| last_peg+1 (8) \| binned (1) | 16 | 12,500 | ✅ identical physics |
| *(design, rejected)* | 24-bit x/y (13 frac) + int16 v (11 frac) | 12 | — | ❌ overflows (see 6.4) |
| **`a89ff57` (current)** | **x/y fix15 with flags in the low 5 bits each; vx/vy int16 with 10 fractional bits** | **12** | **16,000** | ✅ checked by simulation |

### 6.2 Why the 8-fractional-bit attempt failed
The board is **deterministic**: the only randomness is the starting `vx`. A PC simulation of the exact fixed-point physics (20,000 drops, bounciness 0.3) showed:

| Velocity format | Stuck balls | Histogram |
|---|---|---|
| fix15 (reference) | 1 | smooth bell curve, peak at bin 8 |
| 8 fractional bits | **144** | false spikes at bins 1, 3, 13, 15; dip at bin 8 |

- At 1/256 resolution there are only **128 possible starting speeds**, so only 128 possible paths, and the histogram is the sum of those 128 outcomes.
- About **1 in 128 spawns rounds to `vx = 0`**. That ball hits the top peg dead-center and bounces in place forever, because `last_peg` stops the damping from repeating.

**Fix (`b3d6a87`):** keep full fix15 everywhere and pack the flags into spare bits instead. `vx` never exceeds ~18 px/frame, so it fits in 23 bits, and the low 9 bits of that word hold `last_peg + 1` and `binned`. Unpacking is an exact shift, so the physics is bit-identical; 1.6 million pack/unpack round trips had 0 mismatches.

### 6.3 The current 12-byte ball
```c
typedef struct {
  int32_t xm, ym ;   // position (fix15) in bits 31..5 (±2048 px), 5 flag bits in bits 4..0
  int16_t vx, vy ;   // velocity with 10 fractional bits (1/1024 px/frame, ±32 px/frame)
} ball_t ;           // _Static_assert(sizeof(ball_t) == 12)
```
- **meta** (9 bits) = `(last_peg + 1) << 1 | binned`, split as `xm[4:0] = meta & 31` and `ym[4:0] = meta >> 5`.
- **Position keeps full fix15 precision.** On-screen coordinates need only ~11 integer bits, which leaves 5 spare bits in each word.
- **`ballStore()`** clamps positions to ±2047 px (so the `<< 5` can't overflow), rounds velocity to the nearest value, and saturates it to int16.
- **`updateBall`** unpacks everything into locals at the top, runs the unchanged physics, and calls `ballStore()` once at the end.
- **`spawnBall`** changes that make lower-precision velocity safe:
  - **`vx` forced odd** (never exactly 0): no ball can balance on the top peg forever. This also fixes the rare 1-in-20,000 stuck ball that full fix15 had.
  - **±0.5 px random sub-pixel drop position:** keeps enough distinct starting conditions that the histogram stays smooth.

### 6.4 How the layout was chosen (simulation)
| Variant | Problem found |
|---|---|
| Velocity with 11 fractional bits (±16 px/frame) | **Overflows**: at bounciness 1.0 balls reach 16.4 px/frame |
| 24-bit positions (±1024 px) | **Overflows**: at bounciness 1.0 balls fly to x = −634 … 1276 |
| Velocity with 11 fractional bits and no jitter | Lumpy histogram (difference from fix15 ≈ 4× the run-to-run noise) |
| **fix15 positions + 10-bit velocity + odd vx + jitter** | 0 stuck; top speed 16.4 (limit ±32); histogram within ~1–2× the run-to-run noise at bounciness 0.3 / 0.5 / 0.6 / 1.0 |

The packing round trip was checked on 8.2 million cases (every peg value, both flag values, the full position range): 0 mismatches.

---

## 7. Hollow pegs and balls
*Commit `a89ff57`*
- **Pegs:** `fillCircle` → `drawCircle` (on core 1).
- **Balls:** the fast sprite now draws a **ring**: a radius-4 disk minus a radius-3 disk, using the same half-width formula as `fillCircle` (`sqrt_i32(r² + r − i²)`).
  - `ball_dx[i]` is the outer half-width, `ball_hx[i]` the hole half-width (0 = solid row), and each row is at least 1 px thick.
  - `drawRingRow()` draws either the left and right sides, or the whole row where there's no hole. For r = 4 that gives 1–2 px thick sides and solid top and bottom rows.
  - Balls touching the screen edge use `drawCircle`.

---

## 8. Running hot code from SRAM
*Commit `12f680f`. At 13,000 balls, Spare had dropped to 0 µs.*

**The problem:** all code runs from flash through **one 16 KB XIP cache shared by both cores**, so the cores stall on each other's cache misses.

**The changes:**
| Change | Why |
|---|---|
| New `updateAndDrawRange(from, to)` marked **`__no_inline_not_in_flash_func`**, used by both cores | Puts the ball loop and all the inlined draw code in SRAM. **`no_inline` is required:** with plain `__not_in_flash_func`, `-Ofast` inlined it back into the flash-resident protothreads. |
| `updateBall`, `nearestPeg`, `binBall`, `playPegSound` marked `__not_in_flash_func` | The physics runs from SRAM. The last three got inlined into `updateBall`. |
| `drawSpan`'s byte loop replaced with up to 4 direct stores | GCC had turned the loop into **10 `memset` calls per ball**, each a jump back to flash and pure call overhead for 1–4 bytes. `BALL_RADIUS` is now documented as max 4. |

**Checked in the disassembly:**
- `updateAndDrawRange` (1.2 KB) and `updateBall` (0.9 KB) are both at `0x2000xxxx` (SRAM).
- The only remaining calls into flash are `drawCircle` (balls at the screen edge only) and `rand()` (about 50 respawns per frame).
- About 2 KB of extra RAM.

**Result: 13,000 balls at 0 µs spare → 16,000 balls with ~600 µs spare (about +25%).**

---

## 9. Results

### 9.1 Ball count at each step
| Commit | Clock | Max smooth balls | Main technique |
|---|---|---|---|
| `b6e1fb6` | 150 MHz | 1 | Single-ball physics |
| `dd78e34` | 150 MHz | 1 (136 pegs) | O(1) `nearestPeg` |
| `0ebb5c7` | 150 MHz | 100 | Ball array, histogram |
| `a232bc6` | 150 MHz | thousands | Both cores, split by index, semaphore barrier |
| `89e219a` | 150 MHz | 5,000 | Precomputed ball sprite, single-precision floats |
| `06ecd5e` | 150 MHz | 5,200 | Squared distance, FPU inverse, fast path below the board |
| `9de77d0` | 300 MHz | — | Overclock, parallel clear, auto-balance |
| `64bb7eb` | 300 MHz | 10,300 | 20-byte ball |
| `b3d6a87` | 300 MHz | 12,500 | 16-byte packed ball (physics unchanged) |
| `a89ff57` / `12f680f` | 350 MHz | 13,000 (Spare 0) | 12-byte ball, hollow drawing, 350 MHz PLL |
| **`93f067c`** | **350 MHz** | **16,000 (Spare ~600 µs)** | **Hot code in SRAM** |

### 9.2 Current limits
| Resource | Use at 16k balls | Ceiling |
|---|---|---|
| CPU | ~16,070 µs of 16,667 µs on the slower core | ~16.5k balls with almost no margin |
| RAM | `balls[]` = 192 KB, ~14 KB free | ~17k balls at 12 bytes |

---

## 10. Lessons and pitfalls
1. **Measure before optimizing.** Showing Core0 / Core1 / Spare on screen made every later decision a measurement instead of a guess.
2. **Algorithm first.** `nearestPeg` turned 136 checks into 1. Nothing later came close to that gain.
3. **Precompute anything that doesn't change:** peg positions, the ball shape, the sound waveform.
4. **Divide the work, not the data structures.** Giving each core its own range of balls and its own counters avoided locks entirely; the only sync is a few barriers per frame.
5. **A deterministic simulation is sensitive to number precision.** Lower-precision state collapses the variety of paths (a lumpy histogram) and creates fixed points (balls stuck forever). Test layout changes against the full-precision version before flashing.
6. **Check what the compiler actually produced.** `__not_in_flash_func` alone didn't keep the loop in SRAM (it was inlined back), and a harmless-looking byte loop became `memset` calls. Only the disassembly showed either problem.
7. **Overclocking has three coupled parts:** core voltage, an exact PLL setting (not every frequency can be made with refdiv 1), and every peripheral timed in system-clock cycles (here, the VGA PIO programs).
8. **When the limit moves, the next fix changes too.** CPU limit → overclock → RAM limit → smaller ball → CPU limit → run code from SRAM.

---

## 11. Known limitations and harmless races
- **Running over the frame budget tears instead of slowing down.** The DMA swaps buffers at vsync no matter what, and `drawBall` re-reads `current_draw_buffer` per ball. Keep Spare above ~300–500 µs.
- **`rand()` is called from both cores** (respawns) without a lock. This only affects how random the values are.
- **`playPegSound()` checks then starts the DMA** from both cores. At worst a sound restarts.
- **Pixel read-modify-write in `drawSpan`:** two balls from different cores sharing a byte can lose one pixel for one frame.
- **Text is drawn while core 1 is drawing balls**, so a ball can briefly cover the text, or the text background can cover a ball.
- **Drop jitter (±0.5 px)** is a small deliberate change to the starting conditions. It changes the true distribution very slightly, which is physically reasonable.
- **Leftovers:** `FRAME_RATE 33000` is unused. Commit `d0a9659` is titled "try overclock 250mhz" but actually contains the 350 MHz change.
- **The custom flash boot stage 2 probably doesn't apply** (see 5.6).
- **After a reset, balls already in the air still get counted.** The first few hundred counts after a change come from balls dropped under the old setting.
- **High gravity costs more CPU:** faster balls need more collision substeps. 16,000 balls was measured at the default gravity 0.37; check Spare and the LED at gravity 1.00.

---

## 12. Ideas for going further
| Option | Expected gain | Cost / risk |
|---|---|---|
| Overclock to 375 / 400 MHz (D = 15 / 16) | +7% / +14% CPU | Needs `vreg_disable_voltage_limit()` and ~1.35–1.5 V, so more heat. Each frequency also needs an exact PLL setting. |
| Peg sprite instead of `drawCircle` (which draws pixel by pixel) | ~100–300 µs per frame on core 1 | Low |
| Lookup table instead of division in `nearestPeg` | Small | Low |
| Skip drawing balls that are already hidden (at 16k balls the board is covered several times over) | Possibly large | Changes visuals slightly; check whether the lab allows it |
| 8-byte ball | RAM for ~24k balls | Large; precision must be re-checked in simulation; extra unpack cost |
| `DOUBLE_BUFFER_NONE` / `DOUBLE_BUFFER_30` | More RAM / more time per frame | ❌ Tearing, or 30 fps. Breaks "smooth". |

---

## 13. Commit and tag map
| Commit | Message | Content |
|---|---|---|
| `64a9ac7` | rotary encoder down increments and decrements | Encoder state machine and lookup table |
| `b6e1fb6` | ball bounce init set with no dma | One ball, one peg physics |
| `dd78e34` | week1 checkoff | 136 pegs, `nearestPeg`, DMA sound |
| `0ebb5c7` | lab 2 works but the collision model need fix | Ball array, histogram, knob = ball count |
| `a232bc6` | added core 1 and better initial conditions | Two-core split, per-core counters, timing readout |
| `89e219a` | max ball without overclock 5000 | Button modes, E9 workaround, fast sprite |
| `06ecd5e` | max ball 5200 without overclock | Squared distance, FPU inverse, fast path |
| `9de77d0` | overclock impl | Parallel clear, auto-balance, 300 MHz |
| `64bb7eb` | max ball 10300 with overclock | 20-byte ball |
| `b3d6a87` | max ball 12500 with overclock | 16-byte packed ball — **tag `lab2-checkpoint-12500`** |
| `d0a9659` | try overclock 250mhz | *(actually)* 350 MHz with refdiv-2 PLL, D = 14 |
| `a89ff57` | ball restruct to increase max ball | 12-byte ball, hollow drawing |
| `12f680f` | check spare at 13k ball | Hot code in SRAM, `MAX_BALLS` 13000 |
| `93f067c` | max 16k ball on screen with 600us spare | `MAX_BALLS` 16000 |
| `2a571b2` | w2 markdown added | These notes |
| *(uncommitted)* | — | Lab requirements (section 14) and the `[OPT n]` comment rewrite (section 15) |

**Build:** VS Code Pico extension (SDK 2.3.1, toolchain 15_2_Rel1, `PICO_BOARD pico2`), `-Ofast`.
**Test procedure:** turn the knob up in steps of 100 while watching **Spare**. The last count that keeps Spare above ~300–500 µs is the smooth maximum. Let it run a few minutes and check that the histogram is a smooth bell with no stuck balls on the top peg.

---

## 14. Lab requirements: reset, missed-deadline LED, gravity mode
These were added after the optimization work. None of them is on the per-ball hot path, and the hot code is still in SRAM (checked in the disassembly).

### 14.1 Changing a parameter resets the histogram and Fallen count
| Code | Purpose |
|---|---|
| `rot_click()` computes the new clamped value and sets `stats_reset = 1` **only if the value actually changed** | A click at a limit (e.g. bounciness already 1.00) changes nothing, so it resets nothing. Applies to all three knob modes. |
| At the very start of each frame, core 0 checks `stats_reset` and `memset`s `bins_core` and `fallen_core` to 0 | This is the one moment neither core touches the counters: core 1 finished counting last frame (done semaphore) and hasn't been woken to draw the histogram yet. No lock needed. |
| Switching modes with the button doesn't reset | It doesn't change a parameter. |

Balls already counted are not counted again; balls still in the air are counted when they pass the bottom row.

### 14.2 LED on when the 60 fps deadline is missed
| Code | Purpose |
|---|---|
| `extern int start_flag` (from the VGA driver) | The DMA sets it at every vsync, when it swaps the buffers; `draw_start_signal()` clears it as a frame starts. |
| After `done_semaphore` (both cores finished), core 0 **peeks** at `start_flag` | If it's already set again, the buffers swapped mid-draw and the frame was shown half-finished: a missed deadline. An exact test, with no timing estimate. The flag is only read, so the next frame still starts normally. |
| `led_hold = LED_HOLD_FRAMES` (30) on a miss, counting down otherwise; `gpio_put(LED_PIN, led_hold > 0)` | Keeps the LED on ~0.5 s so even a single missed frame is visible; when overloaded it misses every frame and stays on. |
| `missed_frames` shown as `Missed: N` | Counts misses since boot. |
| LED on `PICO_DEFAULT_LED_PIN` (GPIO 25), initialized off in `main()` | The Pico 2's on-board LED. |

**Easy test:** set 16,000 balls and gravity 1.00.

### 14.3 Third knob mode: gravity
| Code | Purpose |
|---|---|
| `ROT_MODE_GRAVITY`, `ROT_NUM_MODES = 3`; the button does `rot_mode = (rot_mode + 1) % ROT_NUM_MODES` | Adds the third state to the cycle. |
| `#define GRAVITY` replaced by `volatile int grav_pct` and `volatile fix15 gravity` (same scheme as bounciness) | Gravity can change while running; `updateBall` adds `gravity` instead of the constant. |
| Range 0.05–1.00, step 0.05, start 0.37 | The 1.00 cap keeps a full-height fall (~29 px/frame) inside the 12-byte ball's ±32 px/frame velocity range (OPT 7). |
| Screen: `Knob: GRAVITY` and `Gravity: 0.37` | Mode names are padded to one width so a shorter name fully overwrites a longer one. |

---

## 15. Optimization index (OPT tags in animation.c)
Each comment block in the code uses the same fields: **Bottleneck → Approach → Effect → Expected / measured**.

| Tag | Optimization | Main code | Bottleneck | Measured result | Details |
|---|---|---|---|---|---|
| OPT 1 | O(1) nearest-peg lookup | `nearestPeg()` | 136 peg tests per ball per substep | Enabled multi-ball (not measured alone) | §3.3 |
| OPT 2 | Split balls across both cores | semaphores, `bins_core`, `updateAndDrawBall`, both anim threads | Core 1 idle | ~2× expected (not measured alone) | §4 Step 2 |
| OPT 3 | Precomputed ball sprite (+ float literals) | `initBallSprite`, `drawSpan`, `drawBall` | `fillCircle` per ball | 5,000 @ 150 MHz | §4 Step 3 |
| OPT 4 | Cheaper collision math | `updateBall` (4a squared distance, 4b FPU 1/sqrt, 4c divide once, 4d fast path) | sqrt + software divides; balls below the board doing the full search | 5,200 @ 150 MHz | §4 Step 4 |
| OPT 5 | Parallel clear + auto split balance | `CLEAR_SPLIT_Y`, top/bot semaphores, `split_pm` | Core 0 clearing alone; fixed split | Shipped with OPT 6 (not measured alone) | §5.1–5.2 |
| OPT 6 | Overclock 300 → 350 MHz | `main()` clock setup, `VGA/*.pio` | CPU at 150 MHz | 300 MHz: 3,150 µs spare at 10k; 350 MHz: 13,000 at 0 µs spare | §5.3–5.5 |
| OPT 7 | Ball struct 24 → 12 bytes | `ball_t`, `ballStore`, `fix2vel`, `spawnBall` | RAM (linker overflow above ~8k) | 10,300 (20 B), 12,500 (16 B), ceiling ~17k (12 B) | §6 |
| OPT 8 | Hot code in SRAM | `updateAndDrawRange` + `__not_in_flash_func` functions, `drawSpan` stores | Shared 16 KB flash cache; memset calls into flash | 13,000 @ 0 µs → **16,000 @ ~600 µs** | §8 |

Code that isn't an optimization (encoder, button, sound, histogram drawing, the new lab features) has short one- or two-line comments only.
