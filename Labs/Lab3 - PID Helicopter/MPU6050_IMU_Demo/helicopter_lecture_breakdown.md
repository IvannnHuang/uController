# ECE 5730 — Helicopter Lab: Lecture Breakdown + Report Checklist

Sources: [Complementary Filters](https://vanhunteradams.com/Pico/ReactionWheel/Complementary_Filters.html) · [Helicopter Lab](https://vanhunteradams.com/Pico/Helicopter/Helicopter.html) · [Course policy (report sections)](https://people.ece.cornell.edu/land/courses/ece4760/EE4760_policy.html)

---

## 1. Lecture → Website mapping

| Lecture point | Where it lives on the site |
|---|---|
| No small-angle approximation — arm swings ~180°, so use full `atan2` | Comp. Filters → *Computing accelerometer angle* (explicitly says helicopter lab can't use small-angle) |
| Accelerometer: clean by hand, explodes in noise once motor spins (vibration = acceleration) | Comp. Filters → *What's bad about the accelerometer?* |
| Accelerometer noise is zero-mean Gaussian → **unbiased** | Comp. Filters → *What's good about the accelerometer?* |
| Gyro measures **rate** (deg/s); zero when stationary; integrate `θ += ω·Δt` | Comp. Filters → *Computing gyro angle* |
| Gyro **drifts** (integration error + inherent random-walk bias) — "dead reckoning" | Comp. Filters → *What's bad about the gyro?* |
| Gyro very low noise over short time | Comp. Filters → *What's good about the gyro?* |
| Trust accel long-term, gyro short-term | Comp. Filters → *Complementary filter* (low-pass accel, high-pass gyro) |
| Flowchart: read → accel angle → gyro Δ = ω·0.001 → weighted sum | Comp. Filters → 4-step algorithm + code snippet |
| Weights: gyro ≈ 0.99–0.999, accel = 1 − gyro (≈ 0.01–0.001) | Comp. Filters → "start with 0.01 / 0.99"; tuning trades bias vs noise |
| `atan2` is nonlinear → white noise in can produce **bias** out → **low-pass raw accel before atan2** | Comp. Filters → *Quick note!* (links Digital Lowpass Filters page) |
| Why not just low-pass accel alone? → **delay = phase lag → destabilizes loop**; gyro removes lag | Not on the site — lecture only (ties to PID pages: phase/gain margin) |
| Over-tuned weight added a few ms delay and destabilized past students' systems | Lecture only |
| Low-pass the PID output for display: `disp += (pwm_on_time - disp) >> 4` (shift = time constant) | Helicopter → Week 2/3: "low-passed motor command signal" on VGA; *Data display* page |
| Same `>> n` filter for raw `ax`, `az` | Helicopter → PID ISR: "possibly low-pass the accelerometer" |
| Accelerometer reads **+1 g up** at rest (normal force; free fall reads 0; Einstein elevator) | Lecture only (conceptual) |
| **Axes:** check IMU silkscreen. Relevant legs ≈ **−a_z and −a_x** (lecturer said double-check) | Site snippet uses `atan2(-ax, ay)+PI` for the *reaction wheel* orientation — **don't copy blindly** |
| **Gyro axis:** rotation is about **Y** (not Z as in the site's `gyro[2]`); arm up = negative Y-rate → check sign of add/subtract | Site snippet uses `gyro[2]` and `complementary_angle - gyro_angle_delta` |
| Test the filter **by hand, motor off**, on VGA before closing the loop | Helicopter → Week 2 checkpoint (VGA display "critical for debugging") |
| Symptom of gyro sign error: angle jumps the **wrong way**, then creeps to correct value | Lecture only |
| Hand-PWM knob test: hard to hold angle near/above 90° — human reaction too slow (delay) | Lecture only (motivates PID + low lag) |
| PID gains: no "right answer," find gains that meet spec, experiment | Helicopter → PID phenomenological/analytical pages |
| Convention: 0° = hanging down, up to ~180° | Site says initial angle ≈ −1.57 rad (hanging down) — pick one convention and state it |

> Note: the attached `.MOV` and `.wav` came through empty, so this is from the pasted transcript only.

---

## 2. Lab report — what to write (don't write it, just cover these)

### Required by policy page
1. **Introduction** — 1D helicopter, IMU + complementary filter, PID at 1 kHz, serial + VGA.
2. **Design & Testing Methods**
   - Hardware: motor circuit on PCB, optoisolator, PWM, I2C to MPU6050.
   - Software: program structure (1 kHz PID ISR, protothreads for serial + VGA, button sequence).
   - Complementary filter: accel `atan2` axes/signs, gyro axis (Y) + sign, Δt = 0.001, weights chosen, accel low-pass shift value.
   - Why low-pass before `atan2` (bias) and why not accel-only (delay/phase).
   - How you verified it: hand-moving arm with motor off, sign-error check.
   - Tests that prove requirements: demo sequence, gain changes via serial take effect immediately.
3. **Documentation** — schematic, heavily commented code listing.
4. **Results** — accuracy, noise, settling times, stable range.
5. **Conclusions** — usability, what you'd change, comments on the lab.
6. **Answers to lab-specific questions** (below).

### Required by Helicopter page
- [ ] **Schematic** of the circuit you built
- [ ] **VGA screenshots**: two traces — (1) low-passed motor control, (2) actual angle — showing the **4-step demo sequence** (0→horizontal, 5 s→+30°, 10 s→−30°, 15 s→horizontal)
- [ ] **How you selected Kp, Ki, Kd** (tuning process, what each did to behavior)
- [ ] **Max/min stable angles** for your gains
- [ ] **Settling times** at different angles (table)
- [ ] **Heavily commented code listing**
- [ ] **AI prompt log** — words exchanged, # code adds/deletes/mods suggested vs accepted

### Worth adding (from lecture)
- [ ] Final complementary-filter weights + accel low-pass shift, and the bias/noise/lag trade-off you saw
- [ ] Display low-pass shift value used for the motor trace
- [ ] Angle convention (0° down vs −1.57 rad) stated clearly
- [ ] Any sign/axis bugs you hit and how you caught them
