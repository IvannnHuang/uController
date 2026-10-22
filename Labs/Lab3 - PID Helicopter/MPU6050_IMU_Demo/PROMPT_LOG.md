# Prompt Log — Lab 3 PID Helicopter (MPU6050_IMU_Demo)

Each entry records the date, the prompt, a summary of the answer, and any code that was generated.
AI assistant: Claude Code (Claude Opus 5.5).

---

## 1. Integrate PWM fan control into the IMU demo
**Date:** 2026-10-21

**Prompt:**
> Can you integrate the pwm fan control into the imu demo

**Answer:**
The IMU demo already set up the PWM slice on GPIO 4/5 (and used the PWM wrap interrupt to read the IMU at 1 kHz), but the duty cycle was stuck at 0. Merged the duty-cycle update from `PWM_Demo/pwm-demo.c` into the existing ISR and added a serial command `p` to set the duty cycle (0–6000). Built successfully.

**Code (imu_demo.c):**
```c
// Globals
volatile int control ;
volatile int old_control ;

// In on_pwm_wrap()
if (control!=old_control) {
    old_control = control ;
    pwm_set_chan_level(slice_num, PWM_CHAN_A, control);
}

// In protothread_serial
else if (classifier=='p') {
    sprintf(pt_serial_out_buffer, "duty cycle (0-%d): ", WRAPVAL);
    serial_write ;
    serial_read ;
    sscanf(pt_serial_in_buffer,"%d", &test_in) ;
    if (test_in >= 0 && test_in <= WRAPVAL) {
        control = test_in ;
    }
}

// In main()
gpio_set_function(PWM_OUT, GPIO_FUNC_PWM);  // was hardcoded 4
```

---

## 2. Comment which code was added
**Date:** 2026-10-21

**Prompt:**
> Can you clearly comment which parts of the code you added

**Answer:**
Wrapped each added block in `// ===== ADDED: ... =====` / `// ===== END ADDED =====` markers, and marked the one changed line with `// CHANGED: was hardcoded 4, now uses PWM_OUT`.

**Code:** comment markers only.

---

## 3. Fan runs at max with duty cycle 0
**Date:** 2026-10-21

**Prompt:**
> something is wrong with the pwm control. when inputtitng a duty cycle of 0 it is still running the fan at max value

**Answer:**
Traced the code path. It correctly sets GPIO 4's level to 0, and the startup level is also 0, so the software logic looked right. Suggested hardware checks: does the fan run at full speed before any input, is the driver circuit inverting (fix: `pwm_set_output_polarity(slice_num, true, false)`), does PWM_Demo behave the same, is the fan on GPIO 4, is the MOSFET gate floating, and was the new `.uf2` flashed.

**Code:** none.

---

## 4. 6000 also runs at full speed; PWM_Demo works
**Date:** 2026-10-21

**Prompt:**
> 6000 still seems to run it at full speed. running the PWM_Demo itself works and lets you change hte fan speed. could it be somehting changing the logic hwen merging the pwm code into imu?

**Answer:**
Compared the merged code against PWM_Demo. The duty-cycle logic, pin, wrap and clock divider were identical. There were no pin conflicts (I2C on 8/9, VGA on 16–21, UART on 0/1), and both builds targeted the Pico 2 (RP2350). Concluded the IMU program probably never reached the PWM setup. `main()` sets up VGA and the IMU first, and `mpu6050_reset()` uses I2C writes with no timeout, which hang if the bus is stuck, so GPIO 4 would float. Asked whether the serial prompt and the VGA traces appear and whether the IMU was connected.

**Code:** none.

---

## 5. Add a complementary filter and display it
**Date:** 2026-10-21

**Prompt:**
> how do I properly add a complementary filter and see it on the screen

**Answer:**
The user had started adding the filter lines, but the variables were undeclared and the low-pass filter was missing. Added the declarations, a first-order IIR low-pass filter (alpha = 1/16) on the accelerometer x/y, starting values seeded from the first reading, display buffers, magenta (accel-only) and yellow (complementary) traces on the top plot shifted by −180°, and a numeric text readout. Noted that the gyro sign, the axis choice, the 1 kHz timestep and the 0.999/0.001 blend may need tuning.

**Code (imu_demo.c):**
```c
#define PI 3.14159265
fix15 filtered_ax, filtered_ay ;
fix15 accel_angle ;
fix15 gyro_angle_delta ;
fix15 complementary_angle ;
fix15 accel_angle_buf[PLOT_WIDTH] ;
fix15 comp_angle_buf[PLOT_WIDTH] ;

// ISR: low pass filter
filtered_ax = filtered_ax + ((acceleration[0] - filtered_ax) >> 4) ;
filtered_ay = filtered_ay + ((acceleration[1] - filtered_ay) >> 4) ;

// ISR: store for display
accel_angle_buf[head] = accel_angle ;
comp_angle_buf[head] = complementary_angle ;

// Draw thread: angle traces
drawPixel(LEFT_EDGE + i, (TOP_PLOT_BOTTOM -
    (int)(NEW_RANGE*((float)((fix2float15(accel_angle_buf[start]) - 180.)-OLD_MIN)/OLD_RANGE))), MAGENTA) ;
drawPixel(LEFT_EDGE + i, (TOP_PLOT_BOTTOM -
    (int)(NEW_RANGE*((float)((fix2float15(comp_angle_buf[start]) - 180.)-OLD_MIN)/OLD_RANGE))), YELLOW) ;

// Draw thread: text readout
setTextSize(2) ;
setTextColor(MAGENTA) ;
setCursor(85, 20) ;
sprintf(screentext, "Accel: %6.1f", fix2float15(accel_angle)) ;
writeString(screentext) ;
setTextColor(YELLOW) ;
setCursor(330, 20) ;
sprintf(screentext, "Comp: %6.1f", fix2float15(complementary_angle)) ;
writeString(screentext) ;
setTextSize(1) ;

// main(): seed filters
filtered_ax = acceleration[0] ;
filtered_ay = acceleration[1] ;
complementary_angle = multfix15(float2fix15(atan2(-filtered_ax, filtered_ay) + PI), oneeightyoverpi);
```

---

## 6. VGA isn't displaying anything
**Date:** 2026-10-21

**Prompt:**
> can you check for bugs the vga isn't displaying anything

**Answer:**
Found two math bugs:
1. A local set of Q15 fixed-point macros (1.0 = 32768) was overriding the Q16 macros in `mpu6050.h` (1.0 = 65536), while `mpu6050.c` still produced Q16 data, so every value was misread by 2×. Removed the local macros.
2. `multfix15(..., 180 / M_PI)` truncated the constant to the integer 57. Replaced it with `oneeightyoverpi`.

Neither would blank the screen: `drawPixel` checks its bounds and the VGA driver is DMA-only. Concluded the program was likely hung in `mpu6050_reset()` before core 1 started, and suggested checking for the serial prompt, scoping GPIO 14/15, and checking the IMU wiring.

**Code (imu_demo.c):**
```c
// FIXED: removed local Q15 fixed-point macros. mpu6050.c / mpu6050.h use
// 15.16 format (1.0 = 65536), so the IMU data must be read with those macros.

// FIXED: second argument must be fixed point (180/M_PI was truncated to the integer 57)
accel_angle = multfix15(float2fix15(atan2(-filtered_ax, filtered_ay) + PI), oneeightyoverpi);
```

---

## 7. Serial terminal broken too
**Date:** 2026-10-21

**Prompt:**
> the serial command terminal seems to be broken as well

**Answer:**
The serial terminal, VGA and fan all failing together confirmed the program was hanging during startup in the I2C/IMU setup. Added a WHO_AM_I check with a timeout, an `imu_ok` flag that skips the IMU reset and the ISR reads if the IMU doesn't respond (so the timeouts can't starve core 0), and startup progress messages printed to the serial terminal.

**Code (imu_demo.c):**
```c
// Global
volatile int imu_ok = 0 ;

// main(), before mpu6050_reset()
printf("\n\rVGA and I2C initialized\n\r") ;
uint8_t who_reg = 0x75 ;
uint8_t who_am_i = 0 ;
int w = i2c_write_timeout_us(I2C_CHAN, ADDRESS, &who_reg, 1, true, 1000) ;
int r = i2c_read_timeout_us(I2C_CHAN, ADDRESS, &who_am_i, 1, false, 1000) ;
if (w == 1 && r == 1 && who_am_i == 0x68) {
    imu_ok = 1 ;
    printf("MPU6050 found (WHO_AM_I = 0x%02x)\n\r", who_am_i) ;
}
else {
    imu_ok = 0 ;
    printf("ERROR: MPU6050 not responding (write=%d read=%d WHO_AM_I=0x%02x)\n\r", w, r, who_am_i) ;
    printf("Check IMU power/ground, SDA on GPIO %d, SCL on GPIO %d\n\r", SDA_PIN, SCL_PIN) ;
}
if (imu_ok) {
    mpu6050_reset();
    mpu6050_read_raw(acceleration, gyro);
    printf("MPU6050 reset done\n\r") ;
}

// ISR
if (imu_ok) mpu6050_read_raw(acceleration, gyro);

// After multicore_launch_core1()
printf("Core 1 launched, starting serial thread\n\r") ;
```

---

## 8. Plots all read 0
**Date:** 2026-10-21

**Prompt:**
> The plots are all just reading at 0 now

**Answer:**
The WHO_AM_I check was too strict. Clone boards often report an ID other than `0x68` (such as `0x70`, `0x72` or `0x98`), so `imu_ok` stayed 0 and every IMU read was skipped. Relaxed the check to accept any device that acknowledges on I2C. Explained how to read the error codes in the ERROR message: `-1` means the IMU didn't respond at its address, `-2` means the bus is stuck (timeout). Also suggested checking the AD0 pin (address 0x69).

**Code (imu_demo.c):**
```c
// Accept any device that answers: clone boards often report an ID other than 0x68
if (w == 1 && r == 1) {
```

---

## 9. Create this prompt log
**Date:** 2026-10-21

**Prompt:**
> Can you record all prompts in a markdown file for the previous prompts and for future prompts. And keep a prompt log of the promt and the answer and code if generated as well as the date.

**Answer:**
Created this file (`PROMPT_LOG.md`) with every prompt so far, and saved a memory note so future sessions keep appending entries here.

**Code:** none (this file).

---

## 10. VGA not displaying again (IMU wiring checked)
**Date:** 2026-10-21

**Prompt:**
> The VGA screen is not displaying again. previously this was because the imu wiring became loose but now I checked this and its still not working.

**Answer:**
The user had removed the WHO_AM_I check and the `imu_ok` guards, so `mpu6050_reset()` could block forever again. The likely cause was a stuck I2C bus: when the Pico resets mid-transfer, the still-powered MPU6050 can hold SDA low, and reflashing doesn't clear it (a power cycle does). Suggested unplugging USB as a quick test, and added a standard I2C bus recovery at startup (up to 9 SCL pulses) that prints whether the bus is free.

**Code (imu_demo.c, in main() before i2c_init):**
```c
gpio_init(SDA_PIN) ;
gpio_init(SCL_PIN) ;
gpio_set_dir(SDA_PIN, GPIO_IN) ;
gpio_pull_up(SDA_PIN) ;
gpio_set_dir(SCL_PIN, GPIO_OUT) ;
gpio_put(SCL_PIN, 1) ;
sleep_us(10) ;
for (int k = 0; k < 9 && !gpio_get(SDA_PIN); k++) {
    gpio_put(SCL_PIN, 0) ;
    sleep_us(5) ;
    gpio_put(SCL_PIN, 1) ;
    sleep_us(5) ;
}
printf("\n\rI2C bus %s\n\r", gpio_get(SDA_PIN) ? "free" : "STUCK (SDA held low)") ;
```

---

## 11. How does the complementary filter work / rotation about +y
**Date:** 2026-10-21

**Prompt:**
> Can you explain how the complementary filter works? What should we see the accel angle and complementary angle change as we rotate about the + y axis of the imu

**Answer:**
- **Concept:** the accel angle (from gravity) never drifts but is noisy, and the gyro integral is smooth but drifts. The filter `angle = 0.999*(angle + rate*dt) + 0.001*accel_angle` acts as a high-pass on the gyro and a low-pass on the accel, with about a 1 s crossover (dt/0.001).
- **Current code:** it measures rotation about **z** (accel x/y, gyro z). Rotating about +y moves gravity between x and z instead, so with a flat IMU the accel angle flips between about 90° and 270°, and the complementary angle gets no gyro input and just drifts slowly toward it. The start-up seed is also commented out, so the complementary angle starts at 0 and takes about 3–5 s to settle.
- **For +y rotation:** use accel x/z and gyro y (code below, suggested only, not applied). Expected behaviour: flat = 0°, a +30° tilt reads +30° on both traces, accel is jittery while the complementary trace is smooth, a fast tilt is tracked with no lag, vibration spikes only the accel, and there's no long-term drift. If the complementary trace moves the wrong way and then creeps back, flip the gyro sign.

**Code (suggested, not applied):**
```c
filtered_ax = filtered_ax + ((acceleration[0] - filtered_ax) >> 4) ;
filtered_az = filtered_az + ((acceleration[2] - filtered_az) >> 4) ;
accel_angle = multfix15(float2fix15(atan2(-filtered_ax, filtered_az)), oneeightyoverpi);
gyro_angle_delta = multfix15(gyro[1], zeropt001) ;
complementary_angle = multfix15(complementary_angle + gyro_angle_delta, zeropt999)
                    + multfix15(accel_angle, zeropt001);
// also: declare fix15 filtered_az; remove "- 180." from the angle plot lines
```

---

## 12. Angles read 80–300° and don't track (arm rotates about +y)
**Date:** 2026-10-21

**Prompt:**
> The IMU setup is an arm that rotates about the +y axis from -180 to 180 deg in the z axis, so the IMU chip lays flat when the arm is held horizontally in the middle of its rotation range. Right now accel ang and comp ang dont seem to make sense because htey range from 80 to 300 deg and dont really track the intermediate movement. is the orientation in the code still wrong?

**Answer:**
Yes. The user had renamed the variable to `filtered_az` and switched to gyro y with a `+`, but `filtered_az` was still filtering `acceleration[1]` (the y axis, which is the rotation axis and stays near 0). With a near-zero denominator, `atan2` flipped toward ±90° (90°/270° after the +PI offset), which matched the 80–300° symptom. Fixed it to use `acceleration[2]`, removed the `+PI` so flat = 0° and the range is ±180°, removed the `-180.` plot shift, and re-enabled the start-up seed using the z axis. It builds cleanly. Noted the wraparound at ±180° (arm pointing straight down), where the accel angle jumps between +180 and −180.

**Code (imu_demo.c):**
```c
// ISR
filtered_az = filtered_az + ((acceleration[2] - filtered_az) >> 4) ;
accel_angle = multfix15(float2fix15(atan2(-filtered_ax, filtered_az)), oneeightyoverpi);

// Draw thread (no -180 shift)
(int)(NEW_RANGE*((float)((fix2float15(accel_angle_buf[start]))-OLD_MIN)/OLD_RANGE))
(int)(NEW_RANGE*((float)((fix2float15(comp_angle_buf[start]))-OLD_MIN)/OLD_RANGE))

// main() seed
filtered_ax = acceleration[0] ;
filtered_az = acceleration[2] ;
complementary_angle = multfix15(float2fix15(atan2(-filtered_ax, filtered_az)), oneeightyoverpi);
```

---

## 13. Closed-loop proportional control of the motor
**Date:** 2026-10-21

**Prompt:**
> How do we add closed loop proportional control of the motor using PWM?

**Answer:**
Added a P controller in the 1 kHz IMU ISR, right after the complementary angle update: `error = desired - complementary_angle`, `duty = Kp * error`, clamped to 0..6000 (the fan only pushes one way). Moved the PWM level update after the controller so each new value is applied in the same interrupt. Added serial commands: `a` target angle, `k` Kp, `c` closed loop on/off (turning it off sets the duty to 0), and `p` manual duty, which now turns the closed loop off. Added a light-blue target line on the top plot and a readout of target, Kp, duty and mode. Enlarged `screentext` from 40 to 80 chars, because the readout line would have overflowed it. Explained that a P-only controller leaves a steady-state error because it needs a nonzero error to hold the arm up against gravity, which is what the I term will fix.

**Code (imu_demo.c):**
```c
// Globals
volatile int closed_loop = 0 ;
volatile fix15 desired_angle = 0 ;
volatile fix15 Kp = int2fix15(100) ;
fix15 angle_error ;
char screentext[80];

// ISR, after complementary filter
if (closed_loop) {
    angle_error = desired_angle - complementary_angle ;
    int u = (int)((((long long)Kp) * ((long long)angle_error)) >> 32) ;
    if (u < 0) u = 0 ;
    if (u > WRAPVAL) u = WRAPVAL ;
    control = u ;
}
if (control!=old_control) {
    old_control = control ;
    pwm_set_chan_level(slice_num, PWM_CHAN_A, control);
}

// Draw thread
drawHLine(LEFT_EDGE, (TOP_PLOT_BOTTOM -
    (int)(NEW_RANGE*((float)((fix2float15(desired_angle))-OLD_MIN)/OLD_RANGE))), PLOT_WIDTH, LIGHT_BLUE) ;
setTextColor(LIGHT_BLUE) ;
setCursor(85, 45) ;
sprintf(screentext, "Target: %6.1f  Kp: %6.1f  Duty: %4d  %s",
    fix2float15(desired_angle), fix2float15(Kp), control, closed_loop ? "CLOSED LOOP" : "MANUAL") ;
writeString(screentext) ;

// Serial thread
else if (classifier=='a') { /* read float -> desired_angle (-180..180) */ }
else if (classifier=='k') { /* read float -> Kp (0..6000) */ }
else if (classifier=='c') { /* 1 = closed_loop on, 0 = off and control = 0 */ }
// 'p' now also sets closed_loop = 0
```

---

## 14. How to tune Kp (bouncing vs. settling ~10° low)
**Date:** 2026-10-22

**Prompt:**
> We added proportional closed loop control. how do we tune kp for the fan to drive the arm to a specified angle? Sometimes it bounces and sometimes its not strong enough to reach the desired angle (~10 deg lower).

**Answer:**
Both symptoms are limits of P-only control, so no single Kp fixes both. The arm needs a nonzero holding duty against gravity, so P settles where `error_ss = u_hold / Kp` (can be checked by finding the holding duty with `p`). Raising Kp shrinks that error, but the arm is a lightly damped pendulum with fan lag, so it overshoots and oscillates, and the `u < 0` clamp lets it free-fall on overshoot. Tuning procedure: raise Kp to sustained oscillation and use about half; add D from the gyro rate to damp it (lets Kp go higher); then add I with anti-windup, or a feedforward holding duty `u_ff`, to remove the offset. Watch the duty readout: swinging 0↔6000 means the gain is too high, pinned at 6000 means the fan can't reach the angle.

**Code (suggested, not applied):** PID + feedforward sketch for the ISR (Kd, Ki, `u_ff`, clamped `error_integral`, `d = Kd * gyro[1]` subtracted).

---

## 15. Add derivative control
**Date:** 2026-10-22

**Prompt:**
> can you add derivative control? also make sure to comment the sections you are changing and add the change log to the markdowns.

**Answer:**
Added a D term to the ISR controller, using the gyro y rate directly (d(error)/dt = −gyro[1] because the target is constant), which avoids the noise of differencing the angle estimate, as recommended in lecture. The control law is now `u = Kp*error − Kd*gyro[1]`, still clamped to 0..6000. Added a `d` serial command (0–6000) to set Kd, which defaults to 0 so behaviour is unchanged until it is set, and added Kd to the VGA readout. Marked the changes with `ADDED` / `CHANGED` comments, added an implementation change log section to `pid_lecture_breakdown.md`, and logged the previous (tuning) prompt as entry 14. Builds cleanly.

**Code (imu_demo.c):**
```c
// Globals
volatile fix15 Kd = int2fix15(0) ;              // gain (duty counts per deg/s, 15.16), 0 = off

// ISR controller
angle_error = desired_angle - complementary_angle ;
long long p_term = ((long long)Kp) * ((long long)angle_error) ;
long long d_term = ((long long)Kd) * ((long long)gyro[1]) ;
int u = (int)((p_term - d_term) >> 32) ;   // CHANGED: was Kp * error only
if (u < 0) u = 0 ;
if (u > WRAPVAL) u = WRAPVAL ;
control = u ;

// Draw thread readout
sprintf(screentext, "Target: %6.1f  Kp: %6.1f  Kd: %6.1f  Duty: %4d  %s",
    fix2float15(desired_angle), fix2float15(Kp), fix2float15(Kd), control, closed_loop ? "CLOSED LOOP" : "MANUAL") ;

// Serial thread
else if (classifier=='d') { /* read float -> Kd (0..6000) */ }
```

---

## 16. Clamp the duty cycle to 4500
**Date:** 2026-10-22

**Prompt:**
> can you clamp the duty cycle to max 4500

**Answer:**
Added `#define DUTY_MAX 4500`. The closed-loop clamp now limits `u` to `DUTY_MAX` instead of `WRAPVAL` (6000), and the manual `p` command only accepts 0–4500. The PWM period (`WRAPVAL` = 6000) is unchanged, so 4500 is 75% duty. Builds cleanly.

**Code (imu_demo.c):**
```c
#define DUTY_MAX 4500

// ISR controller
if (u > DUTY_MAX) u = DUTY_MAX ;   // CHANGED: was WRAPVAL (6000)

// Serial 'p' command
sprintf(pt_serial_out_buffer, "duty cycle (0-%d): ", DUTY_MAX);
if (test_in >= 0 && test_in <= DUTY_MAX) {
```

---

## 17. Add integral control
**Date:** 2026-10-22

**Prompt:**
> Now can you add integral control

**Answer:**
Added an I term to the ISR controller, making it a full PID: `u = Kp*error − Kd*gyro[1] + i_term`, clamped to 0..`DUTY_MAX`. Every 1 ms sample the controller accumulates `Ki*error` (rather than the raw error), so the sum is already in duty counts. That means it can't overflow 15.16 fixed point, and changing Ki doesn't make the output jump. Anti-windup: `i_term` is capped at `i_max` (default 3000; the lecture says to set it a little above the duty that holds the arm at the target) and floored at 0, because the fan can't pull down. The integrator resets to 0 whenever closed loop is off (including after `p` or `c 0`). New serial commands: `i` sets Ki (default 0 = off, suggested start ~0.03) and `m` sets `i_max` (0–`DUTY_MAX`). Added a second VGA readout line showing Ki, I max and the live I term. Builds cleanly.

**Code (imu_demo.c):**
```c
// Globals
volatile fix15 Ki = int2fix15(0) ;
volatile int i_max = 3000 ;
volatile fix15 i_term = 0 ;

// ISR controller
i_term += multfix15(Ki, angle_error) ;
if (i_term > int2fix15(i_max)) i_term = int2fix15(i_max) ;
if (i_term < 0) i_term = 0 ;
int u = (int)((p_term - d_term) >> 32) + fix2int15(i_term) ;
...
else {
    i_term = 0 ;   // controller off -> clear integrator
}

// Draw thread
setCursor(85, 57) ;
sprintf(screentext, "Ki: %7.4f  I max: %4d  I term: %6.1f",
    fix2float15(Ki), i_max, fix2float15(i_term)) ;
writeString(screentext) ;

// Serial thread
else if (classifier=='i') { /* read float -> Ki (0..100) */ }
else if (classifier=='m') { /* read int -> i_max (0..DUTY_MAX) */ }
```

---

## 18. Tuning PID for fast response
**Date:** 2026-10-22

**Prompt:**
> If we want the arm to be very fast response to angle changes, how should we tune the pid parameters

**Answer:**
Speed comes from Kp, and Kd is what lets Kp go high without bouncing. Aim for slight overshoot (about 5–10%), which settles faster than a fully damped response. Procedure, using step tests (e.g. target 0 → 30°): raise Kp until it overshoots, raise Kd until the overshoot is damped, and repeat. Stop when either (a) the duty slams between 0 and `DUTY_MAX` during a step, which means the actuator is saturated and more gain won't help, or (b) the fan chatters at rest, which means Kd is amplifying gyro noise (a low-pass filter on gyro[1] would help). Add Ki last and keep it small. I is slow and winds up during large steps, which causes overshoot, so keep `i_max` tight (holding duty + margin). Physical limits: the rise is limited by `DUTY_MAX` (4500) and the fall by gravity, because the fan can't pull down, so the response is asymmetric. Options for more speed: feedforward of the holding duty, so P doesn't have to do that job; integrating only when the error is small (conditional integration); raising `DUTY_MAX`. Use `t` to slow the plot scroll and see the step response.

**Code:** none.

---
