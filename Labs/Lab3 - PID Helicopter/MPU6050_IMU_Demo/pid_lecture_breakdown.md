# ECE 5730 — Helicopter Lab: PID Lecture Breakdown

Source: [Phenomenological Introduction to PID](https://vanhunteradams.com/PID/PID.html) (math version next lecture: [Analytical PID](https://vanhunteradams.com/PID/PID_Analytical.html))

---

## 1. Lecture → Website mapping

| Lecture point | Where it lives on the site |
|---|---|
| Recap of the 1 kHz ISR: read IMU → low-pass accel → complementary filter → error = desired − measured → PID → PWM | Not on PID page (Helicopter page → *Program organization*) |
| Angle convention: 0° = hanging down, 180° = straight up | Lecture only (PID page uses potentiometer ADC units) |
| System is easy below 90° but **nonlinear above 90°**; thrust ∝ motor speed² | Lecture only |
| Hand-control fails above 90° → too much delay → phase lag → unstable | Lecture only (Analytical page covers phase margin) |
| Why not a lookup table? → open loop is sensitive to altitude (Denver), motor warming, bumps, loads | **Open loop control** (site uses Colorado example) |
| Open loop is fine in deterministic, controlled environments — just not this one | **Open loop control** note |
| Close the loop: measure, compare to target, controller turns error into motor command | **Closing the loop** |
| PID chosen because simple + most common controller in industry | **Closing the loop** |
| Spec: measured and desired traces overlap **pixel for pixel**; recovers from a disturbance | Lecture only |
| **P**: scales instantaneous error. Problem 1: **steady-state error** (at target, error = 0 → motor off) | **Proportional term** |
| **P** problem 2: high Kp → **oscillation** (overshoot back and forth) | **Proportional term** (video) |
| Negative P output = motor off (no reverse thrust) | Lecture only |
| **I**: scales accumulated error (area under curve); removes steady-state error | **Integral term** |
| PI alone is still bouncy/slow; raising Ki makes it worse (integrator adds 90° phase lag) | **Integral term** (overshoot); phase part is Analytical page |
| **D**: scales rate of change of error (slope); opposes P and I when closing fast → damping | **Derivative term** |
| Some overshoot OK here; rocket-on-barge needs none (high Kd) | **Derivative term** |
| Untuned vs tuned demo — identical code, only gains differ | **Derivative term** (two videos) |
| **Integrator windup**: arm held down → I sum grows past saturation → arm overshoots when released | **Integrator windup** |
| Fix: **cap the integrator** | **Integrator windup** — site adds clamp rules: stop accumulating when output saturated *and* output sign = error sign; unclamp when error flips; cap below actuator max |
| **How to pick the cap** (lecture): at hover, P ≈ 0 and D ≈ 0 so **I alone holds the arm**. Find open-loop duty cycle that holds ~90°, add margin | Lecture only |
| D amplifies high-frequency noise (derivative of sine ∝ ω) | **Derivative noise amplification** |
| Old fix #1: analog low-pass filter on potentiometer | **Derivative noise amplification** (op-amp filter) |
| Old fix #2: one-sample difference too small vs noise (~0.25°/sample) → use error(n) − error(n−x) | **Small derivative signal** (site: x = 4) |
| **Best fix (student Sam's idea):** desired angle is constant → d(error)/dt = −d(measured)/dt = **−gyro rate** → **use the gyro output directly for D** | **Lecture only — not on site.** This is the recommended approach for the IMU version |
| **Kp guess**: full duty at ~90° error → ~6000/90 ≈ tens | **Initial guess for Kp** (site's numbers are for ADC/25 MHz; same logic) |
| **Kd guess**: gyro max ≈ 250°/s, comparable to P's error in degrees → Kd also **~tens** | **Initial guess for Kd** — site says 1000s, but that's for ADC differences. **With gyro, use tens** |
| **Ki guess**: sum grows fast → Ki orders of magnitude smaller, start ~1/32 | **Initial guess for Ki** (site also suggests powers of 2 for shifts) |
| **Tuning order**: P only (low) → raise to edge of oscillation → add D to damp → alternate P↑/D↑ until snappy with little overshoot → add a touch of I | **Tuning** |
| **Unit-test each term**: P — pull arm off target, motor speeds up with error. I — Kp = 0, hold arm ~5° off, motor ramps up until saturation. D — hold arm high, drop it, it should catch/slow the fall | Lecture only |
| Observability: VGA plot of measured angle, desired angle, PID output | Lecture only (Helicopter → *Data display*) |
| Optional: plot P, I, D contributions and their sum separately | Lecture only (not required, very helpful) |

> Side note from lecture: diffusion-limited aggregation was mentioned as a possible final project.

---

## 2. Key differences from the website (watch these)
- **D term**: website uses a multi-sample error difference; lecture says **use the gyro rate** instead.
- **Kd scale**: website says 1000s; with gyro, it's **tens**.
- **Kp scale**: website uses a 25000 duty range; yours is **~6000** → Kp in the tens.
- **Integrator cap**: website gives clamp rules; lecture gives a way to pick the value (duty to hover at 90° + margin). Use both.

---

## 3. Adds to the lab report checklist
- [ ] **How you chose Kp, Ki, Kd** — starting guesses (math above) + tuning order you followed
- [ ] Why D uses the gyro (noise argument, d(error)/dt = −θ̇)
- [ ] Integrator cap value and how you found it
- [ ] Unit tests for each term and what you observed
- [ ] VGA screenshots (bonus: separate P/I/D traces)
- [ ] Windup behavior with vs without the cap (if you tested it)
- [ ] Stable angle range — note difficulty above 90° (nonlinear)

---

## 4. Implementation change log (imu_demo.c)
| Date | Change |
|---|---|
| 2026-10-21 | **P control** added in the 1 kHz ISR: `u = Kp * (desired - comp_angle)`, clamped 0..6000. Serial `a` (target), `k` (Kp), `c` (closed loop on/off). |
| 2026-10-22 | **D control** added using the gyro rate (per lecture): `u = Kp*error - Kd*gyro[1]`. Serial `d` sets Kd (default 0 = off). Kd shown on the VGA readout. |
| 2026-10-22 | **Duty cap** lowered to 4500 (`DUTY_MAX`) for both the controller clamp and manual `p`; PWM period (`WRAPVAL` = 6000) unchanged. |
| 2026-10-22 | **I control** added: `i_term += Ki*error` each 1 ms sample, clamped to [0, `i_max`] (anti-windup, default 3000), cleared when closed loop is off. `u = Kp*error - Kd*gyro[1] + i_term`. Serial `i` (Ki, default 0) and `m` (`i_max`). Ki, I max and I term shown on a second VGA readout line. |
