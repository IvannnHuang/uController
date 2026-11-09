"""Report text. Tokens: {{eq:name}} formula image, data-fig/data-tab define numbers,
[[fn:key]] / [[tn:key]] caption labels, [[f:key]] / [[t:key]] references,
{{CODE}}, {{LOG_TABLE}}, {{LOG_ENTRIES}}, {{TOT_*}} filled by build_report.py."""

BODY = r"""
<!-- ======================================================= TITLE -->
<section class="title">
  <div class="course">ECE 5730 &middot; DIGITAL SYSTEMS DESIGN USING MICROCONTROLLERS</div>
  <h1>Lab 3 Report</h1>
  <div class="sub">PID Control of a 1D Helicopter</div>
  <div class="names">Amber Li &nbsp;|&nbsp; Ivan Huang &nbsp;|&nbsp; Zarif Karim</div>
  <div class="date">Thursday lab section &middot; 11.08.2026</div>
  <img src="figures/1d_positive_30.png" style="width:42%">
  <div class="tag">The arm holding +30&deg; above horizontal during the demo sequence.</div>
</section>

<h1 class="sec" style="break-before: page">Contents</h1>
<div class="toc">
  <div>1 &nbsp;Introduction</div>
  <div>2 &nbsp;Mathematical and Physical Background</div>
  <div class="sub">2.1 Measuring angle &middot; 2.2 Complementary filter &middot; 2.3 Plant model &middot; 2.4 PID control &middot;
       2.5 Practical PID problems &middot; 2.6 PWM and the motor circuit &middot; 2.7 Fixed point &middot; 2.8 I2C</div>
  <div>3 &nbsp;Design and Testing Methods</div>
  <div class="sub">3.1 Build order and debugging &middot; 3.2 Motor driver &middot; 3.3 PWM &middot; 3.4 IMU &middot; 3.5 Control ISR &middot;
       3.6 Overcurrent protection and anti-windup &middot; 3.7 Demo sequence &middot; 3.8 VGA &middot; 3.9 Serial &middot; 3.10 Wiring</div>
  <div>4 &nbsp;Documentation</div>
  <div>5 &nbsp;Results</div>
  <div class="sub">5.1 Final gains &middot; 5.2 Demo sequence &middot; 5.3 Settling times &middot; 5.4 Hover duty vs. angle &middot;
       5.5 Stable range &middot; 5.6 Earlier tuning runs</div>
  <div>6 &nbsp;Conclusion</div>
  <div>7 &nbsp;Answers to the Lab Report Questions</div>
  <div>8 &nbsp;Work Distribution and AI Use</div>
  <div>References</div>
  <div>Appendix A &nbsp;Commented Code Listing</div>
  <div>Appendix B &nbsp;AI Prompt Log</div>
</div>

<!-- ======================================================= 1 INTRO -->
<h1 class="sec" style="break-before: auto; margin-top: 22pt">1 &nbsp;Introduction</h1>
<p>We built and controlled a one-degree-of-freedom "helicopter": a lever arm on a hinge with a ducted motor at the
free end. An MPU-6050 IMU on the arm reports acceleration and angular rate over I2C. A Raspberry Pi Pico 2 (RP2350)
fuses the two with a complementary filter to estimate the arm angle, and a PID controller running at exactly 1 kHz
(inside the PWM-wrap interrupt) sets the motor's PWM duty cycle through an optically isolated MOSFET driver.</p>
<p>The target angle and all three gains are set from a serial terminal and take effect on the next 1 ms cycle.
A VGA display plots the measured angle against the target and the controller's motor command in real time.
A pushbutton runs the demo: while it is held, the motor is off and the arm hangs at &minus;90&deg;; on release the
target steps to 0&deg;, then +30&deg; at 5 s, &minus;30&deg; at 10 s and 0&deg; at 15 s, using whatever gains are
loaded. With our final gains (K<sub>p</sub> = 80, K<sub>i</sub> = 0.2, K<sub>d</sub> = 12) the arm reached every
demo angle and settled in 1&ndash;3.6 s, and stayed stable from &minus;90&deg; to about +50&deg;.</p>
<figure data-fig="rig"><img src="figures/rig_top.png" style="width:96%">
<figcaption><b>[[fn:rig]]</b> The rig from above: Pico 2 and VGA adapter on the breadboard, the motor-driver PCB,
the hinge clamped to the bench, the IMU next to the hinge and the ducted motor at the end of the arm.</figcaption></figure>
<p><b>Angle convention.</b> Throughout the report and code, 0&deg; is the arm horizontal, &minus;90&deg; is hanging
straight down (the handout's &minus;1.57 rad starting position) and positive angles are above horizontal. The
course's analytical notes measure &theta; from hanging down instead; where we use their equations,
&theta; = &phi; + 90&deg;, where &phi; is our angle.</p>

<!-- ======================================================= 2 BACKGROUND -->
<h1 class="sec">2 &nbsp;Mathematical and Physical Background</h1>

<h2>2.1 &nbsp;Measuring angle: accelerometer vs. gyroscope</h2>
<p>An accelerometer measures <i>specific force</i>, the acceleration it feels minus gravity. At rest it reads
1 g pointing <i>up</i> (the normal force from the table), and in free fall it reads zero. When the arm is still,
the measured vector is gravity itself, so its direction in the IMU frame gives the tilt (<a>[[f:angles]]</a>a). The arm
pivots about the IMU's y axis, so gravity moves between the x and z axes. Because the arm swings through
140&deg; and more, the small-angle approximation &theta; &asymp; a<sub>x</sub>/g is useless here and we use the full
four-quadrant arctangent:</p>
{{eq:accel}}
<p>The bars mean the readings are low-passed first (Section 2.2). The accelerometer angle never drifts, because gravity
is always there, and its noise is roughly zero-mean, so it is <i>unbiased</i> on average. But any other acceleration
looks like a tilt: motor vibration and the arm's own swinging make it very noisy once the motor runs
(<a>[[f:accelnoise]]</a>).</p>
<p>The gyroscope measures angular rate &omega;<sub>y</sub> (&deg;/s). Integrating it gives an angle that is very smooth over
short times and ignores vibration, but every gyro has a small bias <i>b</i>, so the integral drifts without bound
(dead reckoning):</p>
{{eq:gyro}}
<figure data-fig="angles"><img src="figures/accel_gyro_angles.png" style="width:72%">
<figcaption><b>[[fn:angles]]</b> (a) The accelerometer angle comes from the direction of gravity. (b) The gyro angle
adds rate &times; &Delta;t each step. From the course complementary-filter notes, which label the axes a<sub>y</sub>
and g<sub>z</sub>; on our board the matching axes are a<sub>z</sub> and gyro y.</figcaption></figure>

<h2>2.2 &nbsp;The complementary filter</h2>
<p>Each sensor fails where the other is good: the accelerometer is trustworthy at low frequency (long term), the
gyro at high frequency (short term). Every 1 ms the ISR adds the gyro's angle change to the previous estimate and
nudges the result 0.1% toward the accelerometer angle (<a>[[f:compblock]]</a>):</p>
{{eq:comp}}
<figure data-fig="compblock"><img src="figures/comp_filter_block.png" style="width:86%">
<figcaption><b>[[fn:compblock]]</b> Our complementary filter as implemented in <code>on_pwm_wrap()</code>.</figcaption></figure>
<p><b>Why it is called complementary.</b> Taking this update in the continuous limit (&alpha; = 0.999,
&Delta;t = 1 ms) gives a first-order low-pass on the accelerometer and a first-order high-pass on the gyro angle
with the same time constant:</p>
{{eq:comp_tf}}
<p>The two filters add to exactly 1, so the true angle passes through undistorted at every frequency; only each
sensor's noise is filtered. Below about 1/(2&pi;&tau;) &asymp; 0.16 Hz the estimate follows the accelerometer;
above it, the gyro. Two consequences follow directly from the transfer function:</p>
<ul>
<li><b>Gyro bias becomes a small constant offset instead of drift.</b> A constant bias <i>b</i> integrates to a
ramp b/s&sup2;; through the high-pass it settles to</li>
</ul>
{{eq:bias}}
<ul style="margin-top:-4pt">
<li style="list-style:none">An uncalibrated MPU-6050 can have a bias of a few &deg;/s, so subtracting a measured bias at start-up would be the
next improvement (Section 6).</li>
<li><b>The weight trades noise for bias.</b> The notes suggest 0.99/0.01; we used 0.999/0.001, which moves the
crossover down ten times and keeps more motor vibration out, at the cost of a larger bias offset (&tau; = 1 s instead
of 0.1 s). With the motor running, our accelerometer readout differed from the complementary angle by 2&ndash;5&deg; at any
instant while the complementary trace stayed smooth (compare the two readouts in the screenshots of Section 5.2).</li>
</ul>
<p><b>Low-pass before <code>atan2</code>.</b> <code>atan2</code> is nonlinear, so zero-mean noise on a<sub>x</sub>
and a<sub>z</sub> does not average out after it: the noisy angle comes out <i>biased</i>. We therefore filter the raw
axes first with a first-order IIR, the digital version of an RC filter (forward-Euler discretisation, as derived on
the course Display page):</p>
{{eq:lpf}}
{{eq:lpf_fc}}
<p>This adds about 16 ms of lag, but only to the accelerometer path, which carries 0.1% weight. The gyro path, which
dominates at control frequencies, has no lag. This is why we did not simply low-pass the accelerometer and skip the
gyro: a filter slow enough to remove vibration would add tens of milliseconds of phase lag inside the control loop,
and lag is exactly what destabilises a feedback loop (Section 2.4).</p>

<h2>2.3 &nbsp;Modeling the plant</h2>
<p>The analytical PID notes model the system as a motor (voltage to rotor speed &omega;) in series with the arm
(&omega; to angle). <b>Motor.</b> An armature with resistance R, inductance L and back-EMF constant K, driving
inertia J with viscous drag b, gives a two-pole low-pass:</p>
{{eq:motor_tf}}
<p>Both poles are fast compared with the arm, so from the arm's point of view the motor speed follows the applied
voltage almost instantly. The arm dominates the loop dynamics.</p>
<figure data-fig="forces"><img src="figures/arm_forces.png" style="width:52%">
<figcaption><b>[[fn:forces]]</b> Thrust and gravity on the arm, with &theta; measured from hanging down. From the course
PID notes.</figcaption></figure>
<p><b>Arm.</b> Thrust is roughly K<sub>T</sub>&omega;&sup2;, always perpendicular to the arm; gravity acts on the motor
mass m at distance L; hinge friction is K<sub>f</sub>&theta;&#775;. Treating the arm as a point mass at its end,
the torque balance is</p>
{{eq:torque}}
<p>Linearising about an operating point (&theta;<sub>0</sub>, &omega;<sub>0</sub>) and taking the Laplace transform:</p>
{{eq:lin}}
{{eq:plant_tf}}
<p>This is a lightly damped resonance whose "spring constant" is (g/L) cos &theta;<sub>0</sub>. Three things follow,
and each showed up in lab:</p>
<ul>
<li><b>Hanging down (&theta;<sub>0</sub> = 0)</b> the arm is a pendulum with natural frequency &radic;(g/L): 5.7 rad/s
(0.9 Hz) for the notes' 0.3 m arm. We did not measure our arm's length precisely.</li>
<li><b>Gravity's stiffness changes sign at horizontal</b> (&theta;<sub>0</sub> = 90&deg;, cos = 0). Below horizontal
gravity pulls the arm back toward equilibrium; above it, gravity pushes the arm further away, so above horizontal
only the controller keeps the arm up.</li>
<li><b>The plant gain 2K<sub>T</sub>&omega;<sub>0</sub>/(mL) depends on the operating point.</b> At angles that need
less thrust the motor spins slower, so each extra duty count moves the arm less. One set of fixed gains cannot be
ideal at every angle, which is part of why the stable range is limited (Section 5.5).</li>
</ul>
<p><b>Thrust needed to hover.</b> Setting all derivatives to zero in the torque balance:</p>
{{eq:hover}}
<p>So the ideal point-mass arm needs the most thrust at horizontal and equal thrust at &plusmn;30&deg;
(cos 30&deg; = 0.87). On our rig the duct hangs <i>below</i> the arm (photo in <a>[[f:demo1]]</a>), so the centre of
mass sits a distance d below the arm's centre line. The gravity torque then becomes</p>
{{eq:com_offset}}
<p>which needs <i>more</i> thrust above horizontal than below it. Section 5.4 shows our measured hover duties have
exactly this asymmetry.</p>

<h2>2.4 &nbsp;PID control</h2>
<p>Open-loop control (a lookup table from desired angle to duty cycle) fails here because the thrust needed changes
with the supply voltage, motor temperature, air density and the arm's wiring, and nothing corrects a bump. We close
the loop instead (<a>[[f:closedloop]]</a>): measure the angle, compare it with the target, and let the controller turn the
error into a motor command.</p>
<figure data-fig="closedloop"><img src="figures/closed_loop.png" style="width:78%">
<figcaption><b>[[fn:closedloop]]</b> Closed-loop control. From the course PID notes.</figcaption></figure>
{{eq:pid}}
<ul>
<li><b>Proportional</b> reacts to the error right now (<a>[[f:piterms]]</a>a). Alone it leaves a steady-state error:
holding the arm up needs a non-zero command, and P only produces one if the error is non-zero. Too much
K<sub>p</sub> makes the arm oscillate.</li>
<li><b>Integral</b> reacts to the accumulated error, the area under the curve (<a>[[f:piterms]]</a>b). It removes
steady-state error: at rest P &asymp; 0 and D &asymp; 0, so the I term alone supplies the hover thrust. It adds
90&deg; of phase lag, so K<sub>i</sub> is kept small.</li>
<li><b>Derivative</b> reacts to how fast the error is changing. It opposes fast approaches, which adds damping.</li>
</ul>
<figure data-fig="piterms"><img src="figures/p_i_terms.png" style="width:58%">
<figcaption><b>[[fn:piterms]]</b> (a) P acts on the error at this instant. (b) I acts on the area under the error curve,
positive and negative. From the course PID notes.</figcaption></figure>
<p><b>D from the gyro.</b> The target only changes in steps, so between steps its derivative is zero and</p>
{{eq:dedt}}
<p>We feed the gyro rate straight into the D term (the approach recommended in lecture) instead of differencing the
angle estimate. Differencing multiplies noise by its frequency, and at 1 kHz the change in angle from one sample to
the next is smaller than the noise. Using &minus;&omega;<sub>y</sub> also means a setpoint step produces no
derivative spike ("derivative kick"), because the gyro does not see the target.</p>
<p><b>Discrete law as implemented.</b> Every 1 ms the ISR computes</p>
{{eq:pid_disc}}
<p>where u<sub>lim</sub> is the slew-limited ceiling of Section 3.6. The integrator accumulates K<sub>i</sub>e (already in
duty counts) rather than &Sigma;e, so changing K<sub>i</sub> never makes the output jump. In physical units our final
gains are</p>
{{eq:gains}}
<p>Written as a single transfer function, the PID controller is two zeros and an integrator. Its integral and
derivative times show which timescales each term acts on:</p>
{{eq:pid_zeros}}
{{eq:zeros_val}}
<p>The controller's zeros sit at about 4 rad/s (0.65 Hz), just below the arm's pendulum resonance, which is where the
analytical notes say the derivative's phase lead is needed.</p>
<p><b>What each gain does to stability</b> (from the Bode-plot analysis in the analytical notes). The combined plant
is type 0 (no free integrator). Raising K<sub>p</sub> lifts the whole magnitude curve: the response gets faster and the
steady-state error shrinks, but the gain margin falls. When the loop has a gain of 1 at &minus;180&deg; of phase the
arm oscillates forever, which we saw at K<sub>p</sub> = 120 (<a>[[f:ponly]]</a>). K<sub>d</sub> adds up to +90&deg;
of phase lead around the resonance, which restores margin and lets K<sub>p</sub> go higher. K<sub>i</sub> adds a free
integrator (type 1, zero steady-state error) at the cost of 90&deg; of phase at low frequency.</p>

<h2>2.5 &nbsp;Practical PID problems</h2>
<p><a>[[t:problems]]</a> lists the failure modes the course notes warn about and what our final code does about each.
<a>[[f:windup]]</a> shows the worst one.</p>
<table class="t" data-tab="problems"><tr><th style="width:44%">Problem</th><th>Our fix (final code)</th></tr>
<tr><td>Integrator windup: error keeps accumulating while the arm is held or the motor is saturated, so the arm
overshoots badly when released</td><td>Conditional integration: I only grows if the output is not already at its
limit. I is floored at 0 and capped at <code>i_max</code>, and cleared whenever closed loop is off (button held,
<code>c 0</code>, manual duty) or K<sub>i</sub> is set to 0</td></tr>
<tr><td>Derivative noise: differentiating multiplies noise by its frequency</td><td>D uses the gyro rate; no numerical derivative</td></tr>
<tr><td>Tiny derivative signal: the per-sample angle change at 1 kHz is below the noise</td><td>Same: the gyro measures rate directly</td></tr>
<tr><td>Derivative kick on a setpoint step</td><td>D acts on the measurement (&minus;&omega;<sub>y</sub>), not on the error</td></tr>
<tr><td>Accelerometer noise from motor vibration, and atan2 bias</td><td>IIR low-pass (&tau; = 16 ms) before atan2, then only 0.1% weight on the accelerometer</td></tr>
<tr><td>Motor can only push up; negative command is meaningless</td><td>Output clamped to [0, 6000]; I floored at 0</td></tr>
<tr><td>Inrush current when the command jumps from 0 to full</td><td>Output may rise at most 20 counts per ms (Section 3.6)</td></tr>
</table>
<div class="tcap"><b>[[tn:problems]]</b> PID implementation problems and our fixes.</div>
<figure data-fig="windup"><img src="figures/windup.png" style="width:66%">
<figcaption><b>[[fn:windup]]</b> Integrator windup: the integrator keeps growing past saturation, so the motor stays
saturated long after the arm passes the target. From the course PID notes.</figcaption></figure>

<h2>2.6 &nbsp;PWM and the motor circuit</h2>
<p><b>PWM.</b> GPIO 4 is channel A of PWM slice 2. The slice's counter runs at f<sub>sys</sub>/CLKDIV = 6 MHz and wraps
after 6001 counts:</p>
{{eq:pwm_f}}
<p>The duty cycle is the channel level divided by 6001, so the command has 6001 steps (0.017% each). The motor's
electrical (L/R) and mechanical time constants are much longer than the 1 ms period, so it responds to the average
voltage:</p>
{{eq:pwm_avg}}
<p>The low bandwidth of the 4N35 optoisolator is what keeps the PWM near 1 kHz: its phototransistor needs tens of
microseconds to switch, so a much faster PWM would never fully turn the MOSFET on or off. The same wrap event drives
our control interrupt, so the controller runs at exactly the PWM rate with no separate timer to keep in sync.</p>
<p><b>Why the motor needs protection.</b> A motor's armature is an inductor. Switching off its current quickly produces
a large voltage spike. The notes' example, 1 mH carrying 1 A switched off in 10 ns, gives</p>
{{eq:ldi}}
<p>The 1N4001 flyback diode across the motor gives that current a safe path. The brushes also produce high-frequency
noise (above 100 kHz), which the 0.1 &micro;F ceramic capacitor shunts (electrolytics are too slow). Finally, the 4N35
isolates the Pico completely: the two sides share no ground, and only light crosses between them (Section 3.2).</p>

<h2>2.7 &nbsp;Fixed-point arithmetic</h2>
<p>All ISR math except <code>atan2</code> is fixed point. <code>fix15</code> is a signed 15.16 number in a 32-bit int
(<a>[[f:fix15]]</a>): range &plusmn;32,768 with a resolution of 1/65,536 &asymp; 1.5 &times; 10<sup>&minus;5</sup>.</p>
{{eq:fix}}
<figure data-fig="fix15"><img src="figures/fix15_layout.png" style="width:86%">
<figcaption><b>[[fn:fix15]]</b> fix15 (15.16) bit layout used by <code>mpu6050.h</code>.</figcaption></figure>
<ul>
<li><b>Multiplication</b> uses a 64-bit product then shifts right by 16. In the PID code we shift K<sub>p</sub>&middot;e
right by 32 instead, which turns the product of two 15.16 numbers directly into an integer duty count.</li>
<li><b>Sensor scaling</b> (in <code>mpu6050.c</code>): at &plusmn;2 g the accelerometer gives 16,384 counts per g;
shifting left by 2 gives 65,536 = 1.0 g. At &plusmn;250 &deg;/s the gyro gives 131 counts per &deg;/s;
<code>multfix15(raw, 500&lt;&lt;16)</code> = raw &times; 500 / 65,536 &asymp; raw / 131.</li>
<li><b>Constants are pre-scaled and slightly rounded:</b> 0.001 &rarr; 65 (really 0.000992) and 0.999 &rarr; 65,470.
The gyro step is therefore about 0.8% short, and the PWM period is 1.0002 ms rather than 1 ms. The accelerometer path
corrects both slowly, which is another reason the filter needs a little accelerometer weight.</li>
</ul>
<p>Two bugs we hit came straight from mixing formats (Section 3.1): a stray set of 1.15 macros (1.0 = 32,768) read
the driver's 15.16 data at half scale, and passing <code>180/M_PI</code> as a fix15 argument truncated it to the integer
57. The fix was to use the header's <code>oneeightyoverpi</code> constant (3,754,936 = 57.2958 &times; 65,536).</p>

<h2>2.8 &nbsp;I2C</h2>
<p>I2C is a two-wire, open-drain bus: devices only ever pull SDA and SCL low, and pull-up resistors bring them high, so
any device can hold the bus. Each byte is 8 data bits plus an acknowledge bit. A read of the MPU-6050 writes the
start register address, then issues a <i>repeated start</i> (keeping control of the bus) and reads 6 bytes; the IMU
auto-increments its register pointer. At 400 kHz:</p>
{{eq:i2c}}
<p>So the I2C reads use about 40% of each control period, which is why the rest of the ISR is lean fixed-point code and
all drawing runs on the other core. Open-drain also explains our worst hardware bug: if the Pico resets in the middle
of a read, the still-powered IMU can be left holding SDA low and every later transfer hangs (Section 3.1).</p>

<!-- ======================================================= 3 DESIGN -->
<h1 class="sec">3 &nbsp;Design and Testing Methods</h1>

<h2>3.1 &nbsp;Build order and debugging</h2>
<p>We built and tested in stages, verifying each one on the VGA screen before closing the next loop: motor driver PCB
and open-loop PWM (week 1); IMU, complementary filter, display and P control (week 2); D, I, the demo button and
overcurrent protection (week 3). Most of our debugging time went to start-up hangs and sensor conventions rather than
control code:</p>
<table class="t" data-tab="bugs"><tr><th style="width:26%">Symptom</th><th style="width:38%">Cause</th><th>Fix</th></tr>
<tr><td>Fan at full speed even at duty 0 after merging the PWM demo into the IMU demo</td><td>The program never reached
the PWM setup: <code>mpu6050_reset()</code> uses blocking I2C writes and hung, leaving GPIO 4 floating</td><td>Found by
noticing that VGA and serial were also dead; IMU wiring re-seated</td></tr>
<tr><td>VGA blank, serial dead, again with the wiring fine</td><td>Stuck I2C bus: the IMU held SDA low after a reset
in mid-transfer. Reflashing doesn't clear it, a power cycle does</td><td>Bus recovery at start-up: clock SCL up to 9
times until the IMU releases SDA (<code>main()</code>, lines 568&ndash;586)</td></tr>
<tr><td>Angles wrong by 2&times;</td><td>Local 1.15 fixed-point macros overrode the driver's 15.16 macros</td><td>Removed
the local macros</td></tr>
<tr><td>Angles off by a constant factor</td><td><code>180/M_PI</code> truncated to 57 when passed as fix15</td><td>Use <code>oneeightyoverpi</code></td></tr>
<tr><td>Angles read 80&ndash;300&deg; and didn't track the arm</td><td>The filter used a<sub>y</sub>, the rotation axis
(always near 0), so <code>atan2</code> flipped between &plusmn;90&deg;; plus a leftover +&pi; offset</td><td>Use
a<sub>x</sub>, a<sub>z</sub> and gyro y; remove +&pi; so horizontal = 0&deg;</td></tr>
<tr><td>Complementary angle jumped the wrong way, then crept to the right value</td><td>Gyro sign opposite to the
accelerometer's (the symptom described in lecture)</td><td>Add, rather than subtract, the gyro step</td></tr>
<tr><td>P-only arm settled about 10&deg; low or bounced</td><td>P-only needs a non-zero error to hold the arm up;
higher K<sub>p</sub> oscillates</td><td>Add D (damping), then I (removes the offset)</td></tr>
</table>
<div class="tcap"><b>[[tn:bugs]]</b> Main problems found during development. Appendix B has the full AI prompt log for these sessions.</div>
<p>Before closing the loop we checked the filter by hand with the motor off, tilting the arm and watching both angle
traces on the VGA. This is how we caught the axis and sign problems in <a>[[t:bugs]]</a>.</p>

<h2>3.2 &nbsp;Motor driver circuit</h2>
<p>As the handout requires, the driver is soldered on the course PCB rather than a breadboard
(<a>[[f:schematic]]</a>). The motor runs from its own 5 V supply through an IRLB8721 logic-level N-MOSFET whose gate
is driven at 12 V. The Pico never touches the motor side: GPIO 4 lights the 4N35's LED through 330 &Omega;, and the
phototransistor switches the 12 V gate supply onto the MOSFET gate.</p>
<figure data-fig="schematic"><img src="figures/motor_schematic.png" style="width:84%">
<figcaption><b>[[fn:schematic]]</b> Motor driver schematic (as built on the course PCB). Only light crosses the 4N35;
the Pico and motor sides have separate supplies and grounds.</figcaption></figure>
<ul>
<li><b>4N35 optoisolator:</b> when GPIO 4 is high the phototransistor conducts and pulls the gate toward 12 V, so the
motor runs. When it is low, the <b>10 k&Omega;</b> resistor pulls the gate to ground, so the MOSFET is off. This is the
"extra 10 k" on the PCB the course page asks about: without it the gate would float and the motor could run on its own.
The <b>1 M&Omega;</b> base resistor drains the phototransistor's stored base charge, shortening its fall time.</li>
<li><b>1N4001 flyback diode</b> across the motor catches the inductive spike of Section 2.6.</li>
<li><b>0.1 &micro;F ceramic capacitor</b> across the motor shunts brush noise.</li>
</ul>
<p>We first drove the board with the course PWM demo and confirmed that the motor speed followed the duty cycle set
from the serial terminal, before merging the PWM code into the IMU program (where the <code>n</code> command now sets a
manual duty).</p>

<h2>3.3 &nbsp;PWM configuration</h2>
<p>GPIO 4 and 5 are assigned to PWM slice 2 (channel B on GPIO 5 is set to level 0 and unused). The slice wraps at
<code>WRAPVAL</code> = 6000 with <code>CLKDIV</code> = 25, giving the 999.8 Hz of Section 2.6, and its wrap interrupt
is registered as <code>on_pwm_wrap()</code>. The ISR only writes a new level with <code>pwm_set_chan_level()</code>
when the command changes. <code>DUTY_MAX</code> is 6000 (100%). We used a 4500 cap during early tuning and raised it back
to 6000 for the final version, which also adds the slew limit of Section 3.6.</p>

<h2>3.4 &nbsp;MPU-6050 and I2C</h2>
<p>The IMU is on I2C0 at 400 kHz (SDA GPIO 8, SCL GPIO 9) and is powered from the Pico's 3.3 V. The course driver sets
it up as in <a>[[t:regs]]</a>. In the ISR, <code>mpu6050_read_raw()</code> uses I2C calls with 250 &micro;s timeouts,
so a glitch can cost one sample but can never hang the control loop. The one-time reset in <code>main()</code> still
uses blocking writes, which is why the bus recovery runs first. After the reset, we seed the accelerometer filters and the
complementary angle from the first reading, so the estimate starts at the true angle instead of creeping up from 0.</p>
<table class="t" data-tab="regs"><tr><th>Register</th><th>Value</th><th>Effect</th></tr>
<tr><td>0x6B PWR_MGMT_1</td><td>0x00</td><td>Wake from sleep</td></tr>
<tr><td>0x19 SMPLRT_DIV</td><td>7</td><td>8 kHz / (1 + 7) = 1 kHz sample rate, matching the control rate</td></tr>
<tr><td>0x1B GYRO_CONFIG</td><td>0x00</td><td>&plusmn;250 &deg;/s (131 LSB per &deg;/s)</td></tr>
<tr><td>0x1C ACCEL_CONFIG</td><td>0x00</td><td>&plusmn;2 g (16,384 LSB per g)</td></tr>
<tr><td>0x37 / 0x38</td><td>0x10 / 0x01</td><td>Data-ready interrupt enabled (pin not used; we poll from the PWM ISR)</td></tr>
<tr><td>0x3B / 0x43</td><td>read 6 bytes each</td><td>Accelerometer x, y, z and gyro x, y, z, big-endian 16-bit</td></tr>
</table>
<div class="tcap"><b>[[tn:regs]]</b> MPU-6050 registers used by <code>mpu6050.c</code>.</div>

<h2>3.5 &nbsp;The control ISR</h2>
<p>Everything time-critical runs in <code>on_pwm_wrap()</code> on core 0, once per PWM period. Each call:</p>
<ol>
<li>Clears the slice-2 interrupt flag and toggles GPIO 14 (a 500 Hz square wave on a scope, one edge per ISR).</li>
<li>Reads the IMU (accelerometer then gyro).</li>
<li>Low-passes a<sub>x</sub> and a<sub>z</sub> (shift by 4) and computes the accelerometer angle with <code>atan2</code>.</li>
<li>Updates the complementary filter with gyro y.</li>
<li>Debounces the demo button and steps the demo target (Section 3.7).</li>
<li>If closed loop is on, runs PID with conditional integration and the slew-limited clamp; otherwise clears the integrator.</li>
<li>Writes the PWM level if it changed.</li>
<li>Every 10th call (<code>threshold</code>), stores the angles and duty in 530-entry circular buffers for the display.</li>
</ol>
<p>The controller core, verbatim from <code>imu_demo.c</code> (comments shortened):</p>
<pre class="snip">angle_error = desired_angle - complementary_angle ;              // + means arm is below target
long long p_term = ((long long)Kp) * ((long long)angle_error) ;
long long d_term = ((long long)Kd) * ((long long)gyro[1]) ;      // de/dt = -gyro y
fix15 i_step = multfix15(Ki, angle_error) ;
int pd = (int)((p_term - d_term) &gt;&gt; 32) ;                         // 15.16 x 15.16 -&gt; integer counts
int u_limit = control + DUTY_SLEW ;                                // overcurrent protection: slew limit
if (u_limit &gt; DUTY_MAX) u_limit = DUTY_MAX ;
if (!(i_step &gt; 0 &amp;&amp; pd + fix2int15(i_term) &gt;= u_limit)) i_term += i_step ;  // conditional integration
if (i_term &gt; int2fix15(i_max)) i_term = int2fix15(i_max) ;
if (i_term &lt; 0) i_term = 0 ;
int u = pd + fix2int15(i_term) ;
if (u &lt; 0) u = 0 ;
if (u &gt; u_limit) u = u_limit ;
control = u ;</pre>
<p>Positive error means the arm is below the target and needs more thrust. D is subtracted because
de/dt = &minus;&omega;<sub>y</sub>: an arm rising fast gets less thrust, an arm falling fast gets more.</p>

<h2>3.6 &nbsp;Overcurrent protection and anti-windup</h2>
<p>A setpoint step makes the P term jump (80 &times; 90&deg; = 7200 counts on release from hanging). Stepping a stalled
motor from 0 to full voltage draws a large inrush current, because there is no back-EMF yet to limit it
(I = V/R at &omega; = 0). The final code therefore lets the command <i>rise</i> by at most <code>DUTY_SLEW</code> = 20
counts per 1 ms sample. Decreases are not limited, so the controller can still cut thrust instantly.</p>
{{eq:ulim}}
<p>The ramp is visible in every step of Section 5.2 as a dotted vertical line in the duty trace: one plotted point
every 10 ms is a 200-count jump. 300 ms is short next to the arm's ~1 s response, so it costs little speed.</p>
<p>The slew limit creates a new windup risk: while the output is pinned at the ramp ceiling, the error stays large
and the integrator would keep charging. So integration is <i>conditional</i>: a positive I step is skipped whenever
P + D + I is already at or above <code>u_limit</code>. This is the clamping rule from the course PID notes (stop
integrating when the output is saturated and the error would push it further). Because of this, we left
<code>i_max</code> at 10000, above <code>DUTY_MAX</code>, so the hard cap never binds in practice. The I term is also
floored at 0, since a negative integral could only delay thrust when the arm needs it.</p>

<h2>3.7 &nbsp;Demo button sequence</h2>
<p>The button is on GPIO 15, wired to ground with the internal pull-up (pressed = low). The ISR polls it every 1 ms
and accepts a new state only after it has disagreed with the old one for 20 consecutive samples (20 ms debounce). Since
one ISR call is 1 ms, the sequence is timed by counting calls:</p>
<table class="t" data-tab="demo"><tr><th style="width:22%">Time</th><th>Target and controller state</th></tr>
<tr><td>Button held</td><td>Closed loop off, duty 0, integrator cleared, target &minus;90&deg;: the arm hangs straight down</td></tr>
<tr><td>Release, t = 0</td><td>Closed loop on, target 0&deg; (horizontal)</td></tr>
<tr><td>t = 5 s</td><td>Target +30&deg;</td></tr>
<tr><td>t = 10 s</td><td>Target &minus;30&deg;</td></tr>
<tr><td>t = 15 s</td><td>Target 0&deg;; the sequence ends and the controller keeps holding horizontal</td></tr>
</table>
<div class="tcap"><b>[[tn:demo]]</b> Demo sequence, run with whatever gains are currently loaded. No reset is needed.</div>
<p>The target is written only at the four step times, so a serial <code>a</code> command can still override it in
between.</p>

<h2>3.8 &nbsp;VGA display</h2>
<p>The Pico drives the monitor through the adapter PCB we soldered in Lab 2 (<a>[[f:vgapcb]]</a>): each colour bit
passes through a series resistor, forming a simple resistor DAC with the monitor's 75 &Omega; input. We reused the
course's double-buffered VGA driver (<a>[[f:dma]]</a>): three PIO state machines generate hsync, vsync and the
4-bit colour output, and a DMA chain streams pixel data to them. At each vsync the chain swaps buffers and sets a flag,
giving the drawing thread about 16.7 ms per frame. A frame is 640 &times; 480 &times; 4 bits (two pixels per byte, 320
bytes per row), so the two buffers use about 300 kB of the RP2350's 520 kB SRAM.</p>
<div class="two">
<figure data-fig="vgapcb"><img src="figures/vga_pcb.png" style="width:52%">
<figcaption><b>[[fn:vgapcb]]</b> Our VGA adapter PCB (photographed during Lab 2).</figcaption></figure>
<figure data-fig="dma"><img src="figures/vga_dma.png" style="width:100%">
<figcaption><b>[[fn:dma]]</b> The VGA driver's DMA chain, from lecture.</figcaption></figure>
</div>
<p>Core 1 runs only the drawing thread, so drawing can never delay the control ISR. Each frame it redraws:</p>
<ul>
<li><b>Top plot:</b> complementary angle (yellow) and target line (light blue), &minus;90&deg; to +90&deg; over 150 pixels
(1.2&deg; per pixel).</li>
<li><b>Bottom plot:</b> the controller's motor command <code>control</code> (orange/yellow), 0&ndash;6000 counts over 150
pixels (40 counts per pixel).</li>
<li><b>Text:</b> accelerometer and complementary angles, target, K<sub>p</sub>, K<sub>d</sub>, duty, mode, K<sub>i</sub>,
I max and the live I term.</li>
</ul>
<p>With one stored point per 10 ms, the 530-pixel plot spans 5.3 s; the serial <code>t</code> command changes this. The plotted
command is the controller output itself, sampled every 10 ms, not a separately low-pass-filtered copy. With
K<sub>d</sub> = 12 and the slew limit, the trace was smooth enough to read its shape clearly (Section 5.2). The course
Display page's filter, <code>motor_disp += (control &minus; motor_disp) &gt;&gt; 4</code>, is the same IIR as our
accelerometer filter and would be a one-line addition (Section 6).</p>

<h2>3.9 &nbsp;Serial interface</h2>
<p>The serial thread on core 0 waits (without blocking the ISR) for a one-letter command, prompts for a value,
range-checks it and writes it straight into the <code>volatile</code> globals the ISR reads, so it takes effect on the next
1 ms cycle.</p>
<table class="t" data-tab="serial"><tr><th>Cmd</th><th>Sets</th><th>Units / range</th></tr>
<tr><td><code>a</code></td><td>Target angle</td><td>&minus;90 to +90&deg; (0 = horizontal)</td></tr>
<tr><td><code>p</code></td><td>K<sub>p</sub></td><td>duty counts per degree, 0&ndash;6000</td></tr>
<tr><td><code>i</code></td><td>K<sub>i</sub></td><td>duty counts per degree per ms, 0&ndash;100 (0 also clears the integrator)</td></tr>
<tr><td><code>d</code></td><td>K<sub>d</sub></td><td>duty counts per &deg;/s, 0&ndash;6000</td></tr>
<tr><td><code>m</code></td><td>Integrator cap <code>i_max</code></td><td>0&ndash;6000 duty counts</td></tr>
<tr><td><code>c</code></td><td>Closed loop on / off</td><td>1 / 0 (0 also turns the motor off)</td></tr>
<tr><td><code>n</code></td><td>Manual duty cycle (turns closed loop off)</td><td>0&ndash;6000</td></tr>
<tr><td><code>t</code></td><td>Plot timestep</td><td>ISR samples per plotted point (default 10)</td></tr>
</table>
<div class="tcap"><b>[[tn:serial]]</b> Serial commands.</div>

<h2>3.10 &nbsp;Wiring and system overview</h2>
<table class="t" data-tab="wiring"><tr><th>Signal</th><th>RP2350 pin</th><th>Notes</th></tr>
<tr><td>VGA Hsync / Vsync</td><td>GPIO 16 / 17</td><td>PIO state machines</td></tr>
<tr><td>VGA Green lo / Green hi / Blue / Red</td><td>GPIO 18 / 19 / 20 / 21</td><td>470 &Omega; / 330 &Omega; / 330 &Omega; / 330 &Omega;</td></tr>
<tr><td>MPU-6050 SDA / SCL</td><td>GPIO 8 / 9</td><td>I2C0, 400 kHz; IMU powered from 3.3 V</td></tr>
<tr><td>Motor PWM</td><td>GPIO 4</td><td>Slice 2 channel A, to the 4N35 through 330 &Omega;</td></tr>
<tr><td>(PWM slice 2 B)</td><td>GPIO 5</td><td>Configured, level 0, unused</td></tr>
<tr><td>ISR timing</td><td>GPIO 14</td><td>Toggles every ISR (scope)</td></tr>
<tr><td>Demo button</td><td>GPIO 15</td><td>To GND, internal pull-up, 20 ms debounce</td></tr>
</table>
<div class="tcap"><b>[[tn:wiring]]</b> RP2350 wiring connections.</div>
<figure data-fig="pinout"><img src="figures/pinout.svg" style="width:96%">
<figcaption><b>[[fn:pinout]]</b> Pico 2 pinout with our pin assignments, coloured by subsystem.</figcaption></figure>
<figure data-fig="block"><img src="figures/system_block.svg" style="width:100%">
<figcaption><b>[[fn:block]]</b> System block diagram. Core 0 closes the loop at 1 kHz and runs the serial thread; core 1
only draws. The orange path is the physical feedback through the arm.</figcaption></figure>

<!-- ======================================================= 4 DOCUMENTATION -->
<h1 class="sec">4 &nbsp;Documentation</h1>
<p>Where to find the drawings, listings and data the course policy asks for:</p>
<table class="t" data-tab="docs"><tr><th>Item</th><th>Where</th></tr>
<tr><td>Motor circuit schematic</td><td><a>[[f:schematic]]</a>, Section 3.2</td></tr>
<tr><td>System block diagram</td><td><a>[[f:block]]</a></td></tr>
<tr><td>Pinout and wiring</td><td><a>[[f:pinout]]</a>, <a>[[t:wiring]]</a></td></tr>
<tr><td>Complementary filter</td><td><a>[[f:angles]]</a>, <a>[[f:compblock]]</a>, Section 2.2</td></tr>
<tr><td>IMU registers, serial commands, demo timing</td><td><a>[[t:regs]]</a>, <a>[[t:serial]]</a>, <a>[[t:demo]]</a></td></tr>
<tr><td>VGA adapter and driver</td><td><a>[[f:vgapcb]]</a>, <a>[[f:dma]]</a></td></tr>
<tr><td>Rig photos</td><td><a>[[f:rig]]</a> and the photos in <a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a></td></tr>
<tr><td>VGA screen dumps (demo sequence)</td><td><a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a>; earlier runs in <a>[[f:ponly]]</a>, <a>[[f:accelnoise]]</a></td></tr>
<tr><td>Settling times, hover duties</td><td><a>[[t:settle]]</a>, <a>[[t:hover]]</a></td></tr>
<tr><td>Commented code listing</td><td>Appendix A</td></tr>
<tr><td>AI prompt log</td><td>Appendix B</td></tr>
</table>
<div class="tcap"><b>[[tn:docs]]</b> Documentation index.</div>

<!-- ======================================================= 5 RESULTS -->
<h1 class="sec">5 &nbsp;Results</h1>
<h2>5.1 &nbsp;Final gains</h2>
<p>K<sub>p</sub> = 80 counts/&deg;, K<sub>i</sub> = 0.2 counts/(&deg;&middot;ms), K<sub>d</sub> = 12 counts/(&deg;/s),
<code>i_max</code> = 10000 (non-binding; conditional integration handles windup), output 0&ndash;6000 with a +20 counts/ms
slew limit. One set of gains ran the whole demo sequence without a reset; Section 7 (Q3) explains how we chose them.</p>

<h2>5.2 &nbsp;Demo sequence</h2>
<p><a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a> show the four steps of the button demo, taken from our video of the
checked-off run. Each VGA screen (left) is paired with a photo of the arm holding that angle (right). In every screen,
the top plot is the complementary angle (yellow) against the target (blue), the bottom plot is the motor command on a
0&ndash;6000 scale, and the newest data is at the right.</p>

<figure data-fig="demo1"><div class="pair"><img src="figures/zero.png"><img class="ph" src="figures/1D_zero.png"></div>
<figcaption><b>[[fn:demo1]]</b> <b>t = 0: release, &minus;90&deg; &rarr; 0&deg;.</b> The duty starts at 0 (motor off while
held), ramps up at the slew limit (dotted rise) to about 4100, dips to about 1300 as D brakes the rising arm, then
settles at 3278. The arm comes up from below with no overshoot, and the integrator, which started from 0, pulls in the
last few degrees. Readout at the right edge: target 0.0, complementary angle &minus;0.8&deg;, duty 3278,
I term 3278.5. At rest the I term supplies essentially all of the command, as Section 2.4 predicts.
Right: the arm holding horizontal (seen edge-on), with the duct hanging below the arm.</figcaption></figure>

<figure data-fig="demo2"><div class="pair"><img src="figures/positive_30.png"><img class="ph" src="figures/1d_positive_30.png"></div>
<figcaption><b>[[fn:demo2]]</b> <b>t = 5 s: 0&deg; &rarr; +30&deg;.</b> The P kick (80 &times; 30&deg; = 2400 counts on top of
the 3280-count hover command) ramps the duty to about 5800. The arm overshoots to about +46&deg; and the duty
dips to about 3100 while the extra integral built up during the rise unwinds, then it settles at +30.0&deg;
with duty 3383 and I term 3336.5. Right: the arm at +30&deg;.</figcaption></figure>

<figure data-fig="demo3"><div class="pair"><img src="figures/negative_30.png"><img class="ph" src="figures/1D_negative_30.png"></div>
<figcaption><b>[[fn:demo3]]</b> <b>t = 10 s: +30&deg; &rarr; &minus;30&deg;.</b> The command drops straight to 0, because
decreases are not slew-limited and the motor cannot pull down, so gravity drives the fall. The arm passes the
target falling fast, and P and D call for a burst of about 5000 counts to catch it. The arm still undershoots to about
&minus;56&deg;, rebounds, and the duty hits 0 a second time before settling. The I term lost much of its stored
value during the fall, so the final approach is a slow creep: the duty is still rising (2533, I term 2433.9) with
the arm at &minus;32.8&deg;. Right: the arm at &minus;30&deg;.</figcaption></figure>

<figure data-fig="demo4"><div class="pair"><img src="figures/zero_again.png"><img class="ph" src="figures/1D_zero.png"></div>
<figcaption><b>[[fn:demo4]]</b> <b>t = 15 s: &minus;30&deg; &rarr; 0&deg;.</b> The fastest step. The integrator is already
near the hover value, so a short P kick (duty about 4700) lifts the arm with only about 4&deg; of overshoot, and it
settles at 0.2&deg; with duty 3288 and I term 3307.2. Right: the arm back at horizontal (same pose as
<a>[[f:demo1]]</a>).</figcaption></figure>

<h2>5.3 &nbsp;Settling times</h2>
<table class="t" data-tab="settle"><tr><th>Step</th><th>Settling time (s)</th><th>Peak overshoot (from screen)</th><th>Main limit on the response</th></tr>
<tr><td>&minus;90&deg; &rarr; 0&deg;</td><td>2.74</td><td>none (approaches from below)</td><td>Integrator starts at 0 and must build the hover command</td></tr>
<tr><td>0&deg; &rarr; +30&deg;</td><td>2.38</td><td>&asymp; 16&deg; (peak &asymp; +46&deg;)</td><td>Integral charged during the rise has to unwind</td></tr>
<tr><td>+30&deg; &rarr; &minus;30&deg;</td><td>3.56</td><td>&asymp; 26&deg; (low &asymp; &minus;56&deg;)</td><td>Gravity-driven fall (motor can't pull down); I partly unwound and rebuilds slowly</td></tr>
<tr><td>&minus;30&deg; &rarr; 0&deg;</td><td>0.98</td><td>&asymp; 4&deg;</td><td>Integrator already close to the hover value</td></tr>
</table>
<div class="tcap"><b>[[tn:settle]]</b> Settling times measured from our recording of the demo run. Overshoot was read off the VGA
photos (1.2&deg; per screen pixel, so about &plusmn;3&deg;).</div>
<p>The pattern matches the physics of Sections 2.3&ndash;2.6. Upward steps are pushed by the motor and braked by
gravity and D, so they are well controlled. The downward step is driven by gravity and can only be braked by thrust,
which has to ramp back up from zero, so it overshoots most and settles slowest. In every step the integrator's state
going in decides the tail: it is the term that has to change by the difference in hover command between the two
angles.</p>

<h2>5.4 &nbsp;Hover duty vs. angle</h2>
<p>At rest P &asymp; 0 and D &asymp; 0, so the steady duty measures the thrust needed to hold each angle.</p>
<table class="t" data-tab="hover"><tr><th>Angle</th><th>Duty (I term)</th><th>Duty as % of period</th>
<th>(duty / duty<sub>0&deg;</sub>)&sup2; &asymp; thrust ratio</th><th>Point-mass model cos &phi;</th></tr>
<tr><td>0&deg;</td><td>3278 (3279)</td><td>54.6%</td><td>1.00</td><td>1.00</td></tr>
<tr><td>+30&deg;</td><td>3383 (3337)</td><td>56.4%</td><td>1.07</td><td>0.87</td></tr>
<tr><td>&minus;30&deg;</td><td>2533 (2434), still rising</td><td>42.2%</td><td>&le; 0.60</td><td>0.87</td></tr>
</table>
<div class="tcap"><b>[[tn:hover]]</b> Steady duty at each demo angle, read from the VGA readouts. The thrust ratio assumes thrust &prop;
&omega;&sup2; with &omega; roughly proportional to the average motor voltage.</div>
<p>A symmetric point-mass arm would need the same thrust at &plusmn;30&deg;, 13% less than at horizontal. Ours needs
<i>more</i> at +30&deg; and much less at &minus;30&deg;. This is the centre-of-mass offset of Section 2.3: with the duct
hanging below the arm, the gravity torque is proportional to r cos &phi; + d sin &phi;. Fitting the two ratios gives
d/r &asymp; 0.4&ndash;0.5. That is only a rough estimate, since the &minus;30&deg; duty was still creeping up and thrust
is only approximately &prop; duty&sup2;, but the direction of the asymmetry is clear. It also means the arm's passive
balance point is not exactly at horizontal: by the same model, gravity stops being restoring around
&phi; &asymp; arctan(d/r), roughly 20&ndash;30&deg; above horizontal.</p>

<h2>5.5 &nbsp;Stable range</h2>
<p>With the final gains the arm was stable from <b>&minus;90&deg;</b> (hanging; the controller simply turns the motor off)
up to about <b>+50&deg;</b>. The upper limit varied with which 5 V motor supply we used; above it the arm was no
longer stable with these gains (details in Section 7, Q4).</p>

<h2>5.6 &nbsp;Earlier tuning runs</h2>
<div class="two">
<figure data-fig="ponly"><img src="figures/p_only_kp120.png" style="width:100%">
<figcaption><b>[[fn:ponly]]</b> Early P-only test (K<sub>p</sub> = 120, K<sub>i</sub> = K<sub>d</sub> = 0, target 0&deg;), on an
older build with a &plusmn;250 angle axis. The arm oscillates steadily, about 6.5 cycles in 5.3 s (&asymp; 1.2 Hz):
the edge of stability. The I term was still 3000 from an earlier run, because at that time setting K<sub>i</sub> = 0
did not clear it. The final code clears the I term when K<sub>i</sub> is set to 0.</figcaption></figure>
<figure data-fig="accelnoise"><img src="figures/early_accel_noise.jpg" style="width:100%">
<figcaption><b>[[fn:accelnoise]]</b> Early build with much larger gains (K<sub>p</sub> = 500, K<sub>d</sub> = 300,
K<sub>i</sub> = 5). The bottom plot still showed the raw accelerometer axes (&plusmn;2 g): with the motor running they are
spread across most of the range by vibration, while the complementary angle in the top plot is a clean line. This is
the motivation for the complementary filter in one picture.</figcaption></figure>
</div>

<!-- ======================================================= 6 CONCLUSION -->
<h1 class="sec">6 &nbsp;Conclusion</h1>
<p>Our helicopter met the lab requirements. The arm ran the full 0&deg; / +30&deg; / &minus;30&deg; / 0&deg; demo on one
set of gains without a reset. Every step settled within 3.6 s, gains and target could be changed from the serial
terminal at any time, and the VGA showed the angle, target and motor command live. The results also lined up with the
theory. The complementary filter's 1 s crossover kept vibration out of the estimate. The steady integral equalled
the hover duty, as PID theory predicts. The asymmetric settling and hover duties are what the one-directional actuator
and the arm's offset centre of mass predict.</p>
<p>We learned how to fuse two imperfect sensors, how each PID term shapes the response, and why a motor needs
isolation, a flyback diode and a bypass capacitor. Most of our debugging went to the I2C start-up hang and to
fixed-point and axis conventions, not to the controller.</p>
<p><b>What we would change.</b></p>
<ul>
<li>Plot a low-passed copy of the command (<code>motor_disp</code>, the course Display page's IIR) as the handout
asks, rather than the sampled raw command.</li>
<li>Calibrate the gyro bias at start-up (average a second of readings with the arm still), removing the &tau;&middot;b offset of Section 2.2.</li>
<li>Add a feed-forward hover command based on the r cos &phi; + d sin &phi; model, so the integrator only trims the
remaining error. This should shorten the slow tails, especially after downward steps.</li>
<li>Move the <code>printf</code> on button events out of the ISR. Printing inside the 1 kHz interrupt can stretch one
control period.</li>
<li>Measure the arm length and mass so the plant model can be checked quantitatively.</li>
</ul>

<!-- ======================================================= 7 QUESTIONS -->
<h1 class="sec">7 &nbsp;Answers to the Lab Report Questions</h1>
<p>The helicopter handout asks the report to include the following. Each answer is self-contained and points to the
supporting figures and tables.</p>

<div class="q"><h3>Q1. A schematic of the circuit you built</h3>
<p>See <a>[[f:schematic]]</a>, with the wiring in <a>[[t:wiring]]</a>, <a>[[f:pinout]]</a> and <a>[[f:block]]</a>. GPIO 4
(PWM) drives the 4N35's LED through 330 &Omega;. Its phototransistor switches the 12 V gate supply (through a kill
switch) onto the gate of the IRLB8721 MOSFET, with a 10 k&Omega; gate pull-down and a 1 M&Omega; base resistor for a
fast fall time. The motor runs from a separate 5 V supply with a 1N4001 flyback diode and a 0.1 &micro;F ceramic
capacitor across it. The Pico and motor sides share no ground. The IMU (I2C0, GPIO 8/9), VGA (GPIO 16&ndash;21) and
demo button (GPIO 15) connect to the Pico as in <a>[[t:wiring]]</a>.</p></div>

<div class="q"><h3>Q2. VGA screen dumps of (1) motor control and (2) actual angle, including the four-angle demo</h3>
<p>See <a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a>, one per step of the demo (0&deg;, +30&deg;, &minus;30&deg;, 0&deg;), each paired
with a photo of the arm at that angle. In each, the top trace is the measured angle against the target and the bottom
trace is the motor command (0&ndash;6000). While the button is held the command is 0 and the arm hangs at &minus;90&deg;
(left edge of <a>[[f:demo1]]</a>). Every step shows the slew-limited ramp in the command, and the settled command
matches the integrator, as described in the captions.</p></div>

<div class="q"><h3>Q3. How you selected the three PID gains</h3>
<p><b>Starting values from units.</b> We sized each gain so its term gives a sensible duty count:</p>
<ul>
<li>K<sub>p</sub>: a 90&deg; error (hanging, target horizontal) should call for roughly full duty, so
K<sub>p</sub> &asymp; 6000/90 &asymp; 67, i.e. tens.</li>
<li>K<sub>d</sub>: the gyro rate in &deg;/s is the same order of magnitude as the error in degrees, so K<sub>d</sub>
is also tens. (The course page's "thousands" assumes differencing noisy ADC samples, not a gyro.)</li>
<li>K<sub>i</sub>: the integrator adds K<sub>i</sub>&middot;e a thousand times a second, so K<sub>i</sub> must be orders
of magnitude smaller; we started near 1/32.</li>
</ul>
<p><b>Tuning procedure</b> (the order from lecture and the PID notes), with what we looked for at each stage:</p>
<ol>
<li><b>P only:</b> raise K<sub>p</sub> to find the edge between stability (oscillations die out and the arm settles) and
instability (oscillations grow into large swings). K<sub>p</sub> = 120 gave steady oscillation at about 1.2 Hz
(<a>[[f:ponly]]</a>), so we backed off to K<sub>p</sub> = 80, about two-thirds of that.</li>
<li><b>Add D</b> until the oscillation stops. Our test: push the arm down below the target and let go. It should spring
back up, overshoot once and quickly settle to a stable position. We ended at K<sub>d</sub> = 12.</li>
<li><b>Add I</b> to remove the steady-state error that P and D leave and bring the arm onto the target. Raising
K<sub>i</sub> reaches the target faster, but too much causes overshoot and slow, rolling oscillation (the integrator's
90&deg; of phase lag). We settled on K<sub>i</sub> = 0.2 (T<sub>i</sub> = K<sub>p</sub>/K<sub>i</sub> = 0.4 s). At that rate a 5&deg;
error grows the I term by 1000 counts per second, so it can build the roughly 3300-count hover command within a few
seconds.</li>
<li><b>Check the whole demo</b> with the button and adjust. Conditional integration (Section 3.6) handled windup, so
we left <code>i_max</code> at 10000.</li>
</ol>
<p>The live I-term readout on the VGA (Section 3.8) was the most useful tuning aid: at every steady angle it should
equal the duty, which confirms that P and D have done their job and only the integral is holding the arm up
(<a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a>).</p></div>

<div class="q"><h3>Q4. What are the maximum/minimum angles that produce stable behaviour for your PID gains?</h3>
<p><b>Maximum &asymp; +50&deg;; minimum &minus;90&deg;</b> (0&deg; = horizontal). The maximum depended on which 5 V motor
supply we used. Why the range is limited:</p>
<ul>
<li><b>Minimum.</b> &minus;90&deg; is the hanging rest position. For targets near it the required thrust goes to zero,
the controller output clamps at 0 and gravity holds the arm, so it is trivially stable. The serial interface accepts
targets down to &minus;90&deg;.</li>
<li><b>Maximum.</b> Above the arm's balance point (horizontal for a point mass, somewhat higher for ours, Section 5.4),
gravity's stiffness is negative: tipping further up <i>reduces</i> the restoring gravity torque, so the controller must
supply all of the stability. The further above that point, the stronger this destabilising term (it grows like the sine
of the distance past the balance point), until the margin that K<sub>d</sub> provides runs out.</li>
<li><b>Operating-point dependence.</b> The plant gain 2K<sub>T</sub>&omega;<sub>0</sub>/(mL) changes with angle, and one
fixed set of gains was tuned for the demo range around horizontal.</li>
<li><b>Supply dependence.</b> A different supply changes thrust per duty count (thrust &prop; V&sup2;), which scales the
whole loop gain. The same gains then sit closer to or further from the stability edge, so the maximum angle moved.</li>
</ul></div>

<div class="q"><h3>Q5. What are the settling times at different angles?</h3>
<table class="t"><tr><th>Step</th><th>Settling time</th><th>Overshoot</th></tr>
<tr><td>&minus;90&deg; &rarr; 0&deg; (release)</td><td>2.74 s</td><td>none</td></tr>
<tr><td>0&deg; &rarr; +30&deg;</td><td>2.38 s</td><td>&asymp; 16&deg;</td></tr>
<tr><td>+30&deg; &rarr; &minus;30&deg;</td><td>3.56 s</td><td>&asymp; 26&deg;</td></tr>
<tr><td>&minus;30&deg; &rarr; 0&deg;</td><td>0.98 s</td><td>&asymp; 4&deg;</td></tr></table>
<p style="margin-top:5pt">(Same data as <a>[[t:settle]]</a>.) Upward steps settle in about 1&ndash;2.7 s. The downward step is
slowest (3.56 s) because the motor can only cut thrust: gravity drives the fall, the arm undershoots, and the
integrator has to rebuild. The fastest step (&minus;30&deg; &rarr; 0&deg;, 0.98 s) started with the integrator already close
to the hover value. The slowest upward step (release from &minus;90&deg;) started with the integrator at zero.</p></div>

<div class="q"><h3>Q6. A heavily commented listing of your code</h3>
<p>Appendix A lists <code>imu_demo.c</code>, <code>mpu6050.c</code>, <code>mpu6050.h</code> and <code>CMakeLists.txt</code>
exactly as built and demonstrated. The course VGA driver and protothreads header were used unchanged and are not listed.
Every change from the course MPU-6050 demo is marked in the comments (<code>ADDED</code>, <code>CHANGED</code>,
<code>FIXED</code>, <code>REMOVED</code>), and those sections are shaded in the listing. Sections 2&ndash;3 explain the
code's math and structure.</p></div>

<div class="q"><h3>Q7. A prompt log from any AI tool used for code generation</h3>
<p>Appendix B is the full log of our code-generation sessions with Claude Code (model: Claude Opus 5.5). It has 18 prompts
from Oct 21&ndash;22, 2026, with our prompts verbatim and Claude's responses. Totals: {{TOT_PW}} prompt words and
{{TOT_RW}} logged response words exchanged; {{TOT_CL}} lines of code given. Suggested additions / deletions / modifications:
<b>{{TOT_S}}</b>. Accepted, meaning still in the final code: <b>{{TOT_A}}</b>.</p></div>

<!-- ======================================================= 8 WORK / AI -->
<h1 class="sec" style="break-before:auto; margin-top: 18pt">8 &nbsp;Work Distribution and AI Use</h1>
<p>Amber, Ivan, and Zarif worked together on all parts of the lab. We frequently met outside of our lab sections, and
most of our work was done in person in the lab. Outside of the lab, we communicated frequently to ensure that we were
all aware of the progress that had been made and what the immediate next steps were.</p>
<p><b>AI use.</b> We used Claude Code (Claude Opus 5.5) while writing the program. Every prompt and response is in
Appendix B, and the code it contributed is marked with <code>ADDED</code> / <code>CHANGED</code> / <code>FIXED</code>
comments (shaded in Appendix A). We also used Claude to help organise, typeset and edit this report from our notes,
draft report, photos, screenshots and measurements. Its code suggestions during report writing (a low-passed display
variable, an alternative button routine on GPIO 2 and extra comments) were not merged into our program. All measurements,
photos, screenshots and the hardware are ours.</p>

<h1 class="sec" style="break-before:auto; margin-top: 18pt">References</h1>
<ol style="font-size:9.6pt">
<li>V. H. Adams, <i>PID control of a 1D helicopter</i> (lab handout). https://vanhunteradams.com/Pico/Helicopter/Helicopter.html</li>
<li>V. H. Adams, <i>Complementary filters</i>. https://vanhunteradams.com/Pico/ReactionWheel/Complementary_Filters.html</li>
<li>V. H. Adams, <i>Phenomenological introduction to PID controllers</i>. https://vanhunteradams.com/PID/PID.html</li>
<li>V. H. Adams, <i>Analytical introduction to PID controllers</i>. https://vanhunteradams.com/PID/PID_Analytical.html</li>
<li>V. H. Adams, <i>DC motor circuit and PWM</i>. https://vanhunteradams.com/Pico/Helicopter/MotorCircuit.html</li>
<li>V. H. Adams, <i>Data display</i>. https://vanhunteradams.com/Pico/Helicopter/Display.html</li>
<li>V. H. Adams, <i>Inter-Integrated Circuit (I2C)</i>. https://vanhunteradams.com/Protocols/I2C/I2C.html</li>
<li>V. H. Adams, MPU6050 IMU demo and PWM demo code. https://github.com/vha3/Hunter-Adams-RP2040-Demos</li>
<li>Raspberry Pi Ltd., <i>RP2350 Datasheet</i> (PWM and I2C chapters).</li>
<li>InvenSense, <i>MPU-6000/MPU-6050 Register Map and Descriptions</i>.</li>
<li>B. Land, <i>ECE 4760/5730 course policy</i> (lab report sections). https://people.ece.cornell.edu/land/courses/ece4760/EE4760_policy.html</li>
</ol>

<!-- ======================================================= APPENDIX A -->
<h1 class="sec">Appendix A &nbsp;Commented Code Listing</h1>
<p>These are the files exactly as built and demonstrated (Pico 2 / RP2350, Pico SDK 2.3.1). The program also uses the
course's <code>VGA/vga16_graphics_v3.c/.h</code>, the three VGA PIO programs and <code>pt_cornell_rp2040_v1_4.h</code>,
unchanged. Changes from the course MPU-6050 demo are marked in the comments with <code>ADDED</code>,
<code>CHANGED</code>, <code>FIXED</code> or <code>REMOVED</code>; these are the sections written with AI assistance (Appendix B)
and later edited by us. <span class="legend"></span> marks those lines. Comments are green.</p>
{{CODE}}

<!-- ======================================================= APPENDIX B -->
<h1 class="sec">Appendix B &nbsp;AI Prompt Log</h1>
<p><b>Tool:</b> Claude Code in VS Code, model <b>Claude Opus 5.5</b>. <b>Dates:</b> October 21&ndash;22, 2026.
<b>Source:</b> the prompt log Claude kept in our project (<code>MPU6050_IMU_Demo/PROMPT_LOG.md</code>), reproduced
below. Prompts are verbatim, typos included. Responses are as recorded in that log. Claude kept the log as it went
(from prompt 9 onward, back-filling 1&ndash;8), so a response is sometimes a condensed version of the full chat reply.</p>
<p><b>How we counted.</b> <i>Words</i> are counted from the log: our prompt, and Claude's recorded response (excluding
code). <i>Code lines given</i> counts the C lines in each response. For <i>suggested</i> changes, one addition,
deletion or modification is one distinct change to the program (e.g. a new serial command, a new ISR block, or one
edited statement), not one line. <i>Accepted</i> means the change is still present in the final
<code>imu_demo.c</code> (Appendix A), even if we edited it later. Changes we applied and later removed count as not accepted.</p>
{{LOG_TABLE}}
<div class="tcap" style="margin-top:4pt"><b>Table B1.</b> Prompt log summary (18 prompts). Totals: suggested {{TOT_S}}, accepted {{TOT_A}}
(additions / deletions / modifications).</div>
<p style="font-size:9.4pt"><i>Note:</i> the demo-button sequence and the overcurrent-protection block (slew limit and conditional
integration) are also marked <code>ADDED</code> in Appendix A but were written after the last entry of
<code>PROMPT_LOG.md</code> and are not recorded there, so they are not counted in Table B1.</p>
<h2>Full log</h2>
{{LOG_ENTRIES}}
"""
