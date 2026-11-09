"""Plain-language version of the report text (same facts and figures as content.py, shorter, easier wording).
Same tokens as content.py; build with:  python3 build_report.py simple"""

BODY = r"""
<!-- ======================================================= TITLE -->
<section class="title">
  <div class="course">ECE 5730 &middot; DIGITAL SYSTEMS DESIGN USING MICROCONTROLLERS</div>
  <h1>Lab 3 Report</h1>
  <div class="sub">PID Control of a 1D Helicopter</div>
  <div class="names">Amber Li &nbsp;|&nbsp; Ivan Huang &nbsp;|&nbsp; Zarif Karim</div>
  <div class="date">Thursday lab section &middot; 11.08.2026</div>
  <img src="figures/1d_positive_30.png" style="width:42%">
  <div class="tag">The arm holding +30&deg; above horizontal during the demo.</div>
</section>

<h1 class="sec" style="break-before: page">Contents</h1>
<div class="toc">
  <div>1 &nbsp;Introduction</div>
  <div>2 &nbsp;The Math and Physics</div>
  <div class="sub">2.1 Measuring the angle &middot; 2.2 The complementary filter &middot; 2.3 How the arm moves &middot;
       2.4 PID control &middot; 2.5 PWM and the motor circuit &middot; 2.6 Fixed point and I2C</div>
  <div>3 &nbsp;How We Built and Tested It</div>
  <div class="sub">3.1 Build order and bugs &middot; 3.2 Motor driver &middot; 3.3 PWM and IMU setup &middot; 3.4 The control loop &middot;
       3.5 Overcurrent protection and windup &middot; 3.6 Demo button &middot; 3.7 VGA and serial &middot; 3.8 Wiring</div>
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
<p>Our "helicopter" is a lever arm on a hinge with a small ducted fan at the end. The goal is to make the arm go to
an angle we pick and stay there.</p>
<p>Here's how it works. An MPU-6050 sensor on the arm measures acceleration and spin rate. The Pico 2 combines the
two readings to figure out the arm's angle. A PID controller then decides how hard to run the fan, 1000 times a
second, and sends that out as a PWM signal through an isolated motor driver.</p>
<p>We can change the target angle and the three PID gains from a serial terminal while it runs. A VGA screen plots the
angle, the target and the motor command live. Pressing and releasing a button runs the demo: the arm starts hanging
straight down, then goes to 0&deg;, +30&deg; at 5 s, &minus;30&deg; at 10 s and back to 0&deg; at 15 s.</p>
<p>With our final gains (K<sub>p</sub> = 80, K<sub>i</sub> = 0.2, K<sub>d</sub> = 12), the arm hit every demo angle,
settled in 1&ndash;3.6 s, and stayed stable anywhere from &minus;90&deg; up to about +50&deg;.</p>
<figure data-fig="rig"><img src="figures/rig_top.png" style="width:96%">
<figcaption><b>[[fn:rig]]</b> The setup from above: Pico 2 and VGA adapter on the breadboard, the motor-driver board,
the hinge clamped to the bench, the IMU next to the hinge, and the fan at the end of the arm.</figcaption></figure>
<div class="callout"><p><b>Angles in this report:</b> 0&deg; means the arm is level, &minus;90&deg; means it's hanging
straight down, and positive means above level. (The course's analytical notes measure &theta; from hanging down
instead, so when we borrow their equations, &theta; = &phi; + 90&deg;, where &phi; is our angle.)</p></div>

<!-- ======================================================= 2 BACKGROUND -->
<h1 class="sec">2 &nbsp;The Math and Physics</h1>

<h2>2.1 &nbsp;Measuring the angle</h2>
<p>We have two sensors, and each one is good at a different thing.</p>
<p><b>The accelerometer</b> feels gravity. When the arm is still, the only thing it measures is gravity, so the
direction of that reading tells us which way is down, and so how tilted the arm is (<a>[[f:angles]]</a>a). The arm
rotates about the sensor's y axis, so gravity shifts between the x and z axes. Since the arm swings through
well over 90&deg;, we can't use a small-angle shortcut; we use the full arctangent:</p>
{{eq:accel}}
<p>The good part: gravity never goes away, so this angle never drifts. The bad part: the sensor can't tell gravity apart
from any other push. Once the fan is running, vibration and the arm's own motion make this reading really noisy
(<a>[[f:accelnoise]]</a>).</p>
<p><b>The gyroscope</b> measures how fast the arm is rotating (&deg;/s). Add up that rate over time and you get an angle
that's smooth and ignores vibration. The catch is that every gyro has a small built-in error <i>b</i>, and adding it up
over time makes the angle slowly drift away (after t seconds it's off by about b&middot;t). Each step we just add
rate &times; time:</p>
{{eq:gyro_s}}
<figure data-fig="angles"><img src="figures/accel_gyro_angles.png" style="width:72%">
<figcaption><b>[[fn:angles]]</b> (a) The accelerometer angle comes from the direction of gravity. (b) The gyro angle
adds up rate &times; time each step. From the course notes, which call the axes a<sub>y</sub> and g<sub>z</sub>;
on our board they're a<sub>z</sub> and gyro y.</figcaption></figure>

<h2>2.2 &nbsp;The complementary filter</h2>
<p>So the accelerometer is right in the long run but jumpy, and the gyro is smooth but drifts. The complementary filter
uses both. Every 1 ms, it takes the last angle, adds the gyro's change, and then nudges the result 0.1% of the way toward
the accelerometer's angle (<a>[[f:compblock]]</a>):</p>
{{eq:comp}}
<figure data-fig="compblock"><img src="figures/comp_filter_block.png" style="width:86%">
<figcaption><b>[[fn:compblock]]</b> Our complementary filter, as written in <code>on_pwm_wrap()</code>.</figcaption></figure>
<p><b>Why "complementary"?</b> The two weights add up to 1. For slow changes (slower than about 1 second, the filter's
time constant &tau;) we trust the accelerometer, and for fast changes we trust the gyro. The real angle gets through
untouched; only each sensor's own noise gets filtered out.</p>
<ul>
<li><b>Gyro drift turns into a small fixed offset</b> (about &tau;&middot;b) instead of growing forever. A gyro error of
1&deg;/s would leave us about 1&deg; off.</li>
<li><b>Our weights.</b> The notes suggest 0.99/0.01. We used 0.999/0.001, which leans harder on the gyro and keeps more
fan vibration out, at the cost of a bigger drift offset. With the fan running, the accelerometer readout bounced 2&ndash;5&deg;
away from the filtered angle while the filtered angle stayed smooth (compare the two readouts in Section 5.2).</li>
</ul>
<p><b>Smoothing before <code>atan2</code>.</b> Noise doesn't average out nicely after a nonlinear function like
<code>atan2</code>; it shifts the result. So we first smooth the raw a<sub>x</sub> and a<sub>z</sub> with a simple
digital filter that works like an RC circuit (in the code it's a right-shift by 4):</p>
{{eq:lpf_s}}
<p>That adds about 16 ms of delay, but only to the accelerometer, which only has 0.1% say in the answer. The gyro path
has no delay. That's the whole reason to use a gyro: if we tried to just heavily smooth the accelerometer instead,
the delay would land inside the control loop, and delay is what makes feedback loops unstable.</p>

<h2>2.3 &nbsp;How the arm moves</h2>
<p><b>The motor</b> speeds up and slows down much faster than the arm swings, so for our purposes the fan speed just follows
the voltage. The arm is the slow part, so the arm is what we have to control.</p>
<figure data-fig="forces"><img src="figures/arm_forces.png" style="width:52%">
<figcaption><b>[[fn:forces]]</b> Thrust and gravity on the arm, with &theta; measured from hanging down. From the course
PID notes.</figcaption></figure>
<p><b>The arm.</b> Three torques act on it: thrust from the fan (about K<sub>T</sub>&omega;&sup2;), gravity pulling the
fan's mass down, and friction in the hinge. Thrust minus gravity minus friction equals how fast the arm speeds up:</p>
{{eq:torque}}
<p>For small wiggles around one angle, the arm acts like a mass on a spring, where gravity is the spring. That explains a
few things we saw in lab:</p>
<ul>
<li><b>Hanging down,</b> the arm is just a pendulum. It swings back and forth on its own and barely damps out.</li>
<li><b>The spring flips at horizontal.</b> Below level, gravity pulls the arm back toward hanging. Above level,
gravity pushes it further away. So above level, the controller is the only thing keeping the arm up.</li>
<li><b>The arm responds differently at different angles.</b> How much one extra duty count moves the arm depends on
how fast the fan is already spinning, so it depends on where the arm is. One fixed set of gains can't be perfect everywhere, which is part of why
the stable range has limits (Section 5.5).</li>
</ul>
<p><b>Thrust needed to hover.</b> When the arm is sitting still, thrust exactly cancels gravity (&phi; is our angle,
0&deg; = level):</p>
{{eq:hover_s}}
<p>For a simple arm with all the mass on its centre line, that means the most thrust at level and the same thrust at
+30&deg; and &minus;30&deg;. But on our rig the fan hangs <i>below</i> the arm (see the photo in <a>[[f:demo1]]</a>), so
the centre of mass sits a bit below the arm's line, a distance d. Then gravity's torque becomes</p>
{{eq:com_offset}}
<p>and the arm needs <i>more</i> thrust above level than below. Our measurements in Section 5.4 show exactly that.</p>

<h2>2.4 &nbsp;PID control</h2>
<p>A lookup table from angle to duty wouldn't work: the thrust needed changes with the supply, motor temperature and
so on, and a table can't fix a bump. So we use feedback
(<a>[[f:closedloop]]</a>): measure the angle, compare it to the target, and turn the error into a motor command.</p>
<figure data-fig="closedloop"><img src="figures/closed_loop.png" style="width:78%">
<figcaption><b>[[fn:closedloop]]</b> Closed-loop control. From the course PID notes.</figcaption></figure>
{{eq:pid}}
<ul>
<li><b>P (proportional)</b> pushes harder the further the arm is from the target (<a>[[f:piterms]]</a>a). On its own it
always leaves the arm a bit low: P only outputs thrust when there's error, and holding the arm up needs thrust.
Too much P and the arm oscillates.</li>
<li><b>I (integral)</b> adds up the error over time, the area under the curve (<a>[[f:piterms]]</a>b). It keeps growing
until the error is gone, so it fixes P's "a bit low" problem. Once the arm is settled, P and D are basically zero and
the I term is the thing holding the arm up. Too much I makes the arm overshoot and wobble slowly.</li>
<li><b>D (derivative)</b> looks at how fast the error is changing. It brakes fast motion, which calms down overshoot
and oscillation.</li>
</ul>
<figure data-fig="piterms"><img src="figures/p_i_terms.png" style="width:58%">
<figcaption><b>[[fn:piterms]]</b> (a) P acts on the error right now. (b) I acts on the total area under the error curve.
From the course PID notes.</figcaption></figure>
<p><b>Getting D from the gyro.</b> The target only changes in jumps, so between jumps the rate of change of the error
is just minus the arm's spin rate: de/dt = &minus;&omega;<sub>y</sub>. So we plug the gyro reading straight into D, as suggested in lecture. Taking the difference between angle samples
would be way noisier: at 1 kHz the angle barely changes from one sample to the next, so you'd mostly be measuring
noise. A bonus is that D doesn't spike when the target jumps (no "derivative kick"), because the gyro doesn't know
about the target.</p>
<p><b>What the code actually does every 1 ms:</b></p>
{{eq:pid_disc}}
<p>u<sub>lim</sub> is a ramp limit we explain in Section 3.5. The I term stores K<sub>i</sub>&middot;e added up (already in
duty counts), so changing K<sub>i</sub> on the fly never makes the output jump. In real units, our final gains are:</p>
{{eq:gains}}
<p><b>What each gain does to stability</b> (from the Bode plots in the analytical notes): more K<sub>p</sub> makes the
arm faster and closer to the target, but at some point it oscillates forever. We saw that at K<sub>p</sub> = 120
(<a>[[f:ponly]]</a>). K<sub>d</sub> adds back stability margin, which lets K<sub>p</sub> go higher. K<sub>i</sub> gets
rid of the leftover error but costs some stability, so it stays small.</p>

<p><b>Common PID problems and how we handled them.</b> The course notes warn about a few things that go wrong in
practice. <a>[[t:problems]]</a> lists them with our fix for each, and <a>[[f:windup]]</a> shows the worst one.</p>
<table class="t" data-tab="problems"><tr><th style="width:44%">Problem</th><th>Our fix</th></tr>
<tr><td>Integrator windup: I keeps growing while the arm is held or the motor is maxed out, so the arm overshoots
badly when it's let go</td><td>Only let I grow if the output isn't already at its limit. I can't go below 0 or above
<code>i_max</code>, and it's reset whenever the loop is off (button held, <code>c 0</code>, manual duty) or K<sub>i</sub>
is set to 0</td></tr>
<tr><td>Taking a derivative amplifies noise</td><td>D uses the gyro rate directly</td></tr>
<tr><td>At 1 kHz the angle barely changes between samples</td><td>Same: the gyro measures rate directly</td></tr>
<tr><td>D spikes when the target jumps</td><td>D uses the gyro, which doesn't see the target</td></tr>
<tr><td>Fan vibration makes the accelerometer noisy</td><td>Smooth it before <code>atan2</code>, then give it only 0.1% weight</td></tr>
<tr><td>The fan can only push up, so a negative command means nothing</td><td>Output kept between 0 and 6000; I kept &ge; 0</td></tr>
<tr><td>Big current surge when the command jumps from 0 to full</td><td>Output can rise at most 20 counts per ms (Section 3.5)</td></tr>
</table>
<div class="tcap"><b>[[tn:problems]]</b> Practical PID problems and our fixes.</div>
<figure data-fig="windup"><img src="figures/windup.png" style="width:66%">
<figcaption><b>[[fn:windup]]</b> Integrator windup: I keeps growing after the motor is already maxed out, so the motor
stays maxed long after the arm passes the target. From the course PID notes.</figcaption></figure>

<h2>2.5 &nbsp;PWM and the motor circuit</h2>
<p><b>PWM</b> means switching the motor fully on and off very fast and changing what fraction of the time it's on.
GPIO 4 is channel A of PWM slice 2. Its counter counts to 6000 and starts over:</p>
{{eq:pwm_f}}
<p>The motor is way too slow to follow 1 kHz switching, so it just responds to the average voltage. A duty level of
3280 out of 6001 is like giving the motor 2.7 V:</p>
{{eq:pwm_avg}}
<p>Why only 1 kHz? The 4N35 optoisolator is slow (it takes tens of microseconds to switch), so a much faster PWM would
never fully turn the MOSFET on or off. We also use the same counter wrap to trigger our control loop, so the controller
runs at exactly the PWM rate without needing a separate timer.</p>
<p><b>Why the motor needs protection.</b> A motor coil is an inductor, and inductors hate having their current cut off
suddenly. The notes' example (1 mH, 1 A, switched off in 10 ns) gives a huge voltage spike:</p>
{{eq:ldi}}
<p>The 1N4001 diode across the motor gives that current somewhere safe to go. The 0.1 &micro;F ceramic capacitor soaks up
high-frequency noise from the motor brushes. And the 4N35 keeps the Pico completely separate from the motor side:
they share no ground, and only light crosses between them (Section 3.2).</p>

<h2>2.6 &nbsp;Fixed point and I2C</h2>
<p><b>Fixed point.</b> Floating-point math is slow on the Pico, so the ISR does almost everything (except
<code>atan2</code>) with <code>fix15</code>: a 32-bit integer where the bottom 16 bits are the fraction
(<a>[[f:fix15]]</a>). 1.0 is stored as 65,536.</p>
{{eq:fix}}
<figure data-fig="fix15"><img src="figures/fix15_layout.png" style="width:86%">
<figcaption><b>[[fn:fix15]]</b> fix15 bit layout used by <code>mpu6050.h</code>.</figcaption></figure>
<p>To multiply, do the product in 64 bits and shift right by 16 (in the PID code we shift by 32, which gives a whole-number
duty count directly). Constants get rounded (0.001 becomes 65), which makes the gyro step about 0.8% short, but the
accelerometer slowly corrects for that. Two of our bugs came from mixing number formats (Section 3.1).</p>
<p><b>I2C</b> is the two-wire bus the IMU talks on. Devices can only pull the wires low; resistors pull them back high.
To read the IMU, the Pico sends the register address and then reads 6 bytes back. At 400 kHz:</p>
{{eq:i2c}}
<p>So reading the sensor takes about 40% of every 1 ms loop. That's why the rest of the ISR is lean integer math and
all the drawing happens on the other core. The "only pull low" design also explains our worst bug: if the Pico resets
in the middle of a read, the IMU can get stuck holding the data line low, and every transfer after that hangs
(Section 3.1).</p>

<!-- ======================================================= 3 DESIGN -->
<h1 class="sec">3 &nbsp;How We Built and Tested It</h1>

<h2>3.1 &nbsp;Build order and bugs</h2>
<p>We built it one piece at a time and checked each piece on the VGA screen before moving on. Week 1: motor driver board
and plain PWM. Week 2: IMU, complementary filter, display and P control. Week 3: D, I, the demo button and overcurrent
protection. Most of our debugging time went to start-up hangs and sensor axes, not the controller itself:</p>
<table class="t" data-tab="bugs"><tr><th style="width:26%">What we saw</th><th style="width:38%">Why</th><th>Fix</th></tr>
<tr><td>Fan at full speed even at duty 0 after merging the PWM code into the IMU code</td><td>The program never got to the
PWM setup: the IMU reset hung on I2C, leaving GPIO 4 floating</td><td>Noticed VGA and serial were dead too; re-seated the
IMU wiring</td></tr>
<tr><td>VGA blank and serial dead again, with the wiring fine</td><td>Stuck I2C bus: the IMU was holding the data line low
after a reset mid-transfer. Reflashing doesn't fix it; unplugging does</td><td>At start-up, pulse the clock line up to 9
times until the IMU lets go (<code>main()</code>, lines 568&ndash;586)</td></tr>
<tr><td>Angles off by 2&times;</td><td>Leftover fixed-point macros in a different format</td><td>Deleted them</td></tr>
<tr><td>Angles off by a constant factor</td><td><code>180/M_PI</code> chopped to 57</td><td>Use <code>oneeightyoverpi</code></td></tr>
<tr><td>Angles read 80&ndash;300&deg; and didn't follow the arm</td><td>We were using a<sub>y</sub>, the axis the arm spins
around (always near 0), plus a leftover +&pi;</td><td>Use a<sub>x</sub>, a<sub>z</sub> and gyro y; remove +&pi; so level = 0&deg;</td></tr>
<tr><td>Filtered angle jumped the wrong way, then crept back</td><td>Gyro sign was backwards compared to the
accelerometer (the symptom from lecture)</td><td>Add the gyro step instead of subtracting it</td></tr>
<tr><td>With P only, the arm sat about 10&deg; low or bounced</td><td>P needs some error to make any thrust; more P
oscillates</td><td>Add D (calms it), then I (removes the offset)</td></tr>
</table>
<div class="tcap"><b>[[tn:bugs]]</b> Main problems we hit. Appendix B has the AI prompt log for these sessions.</div>
<p>Before closing the loop, we tested the filter by hand with the fan off: tilt the arm, watch both angle traces on the
screen. That's how we caught the axis and sign problems.</p>

<h2>3.2 &nbsp;Motor driver circuit</h2>
<p>As required, the driver is soldered on the course PCB (<a>[[f:schematic]]</a>). The motor runs off its own 5 V supply
through an IRLB8721 MOSFET with a 12 V gate drive. The Pico never touches the motor side: GPIO 4 lights the LED inside
the 4N35 through 330 &Omega;, and the light switches the 12 V onto the MOSFET gate.</p>
<figure data-fig="schematic"><img src="figures/motor_schematic.png" style="width:84%">
<figcaption><b>[[fn:schematic]]</b> Motor driver schematic (as built on the course PCB). Only light crosses the 4N35;
the two sides have separate supplies and grounds.</figcaption></figure>
<ul>
<li><b>4N35:</b> GPIO 4 high &rarr; gate pulled up to 12 V &rarr; motor on. GPIO 4 low &rarr; the <b>10 k&Omega;</b>
resistor pulls the gate to ground &rarr; motor off. That's the "extra 10 k" the course page asks about: without it the
gate would float and the motor could turn on by itself. The <b>1 M&Omega;</b> resistor helps the 4N35 switch off faster.</li>
<li><b>1N4001 diode</b> across the motor catches the voltage spike from Section 2.5.</li>
<li><b>0.1 &micro;F capacitor</b> across the motor soaks up brush noise.</li>
</ul>
<p>We first tested the board with the course PWM demo and checked that the fan speed followed the duty cycle, then
merged the PWM code into the IMU program (where the <code>n</code> command now sets a manual duty).</p>

<h2>3.3 &nbsp;PWM and IMU setup</h2>
<p><b>PWM.</b> GPIO 4 and 5 are on PWM slice 2 (GPIO 5 is set to 0 and not used). The slice counts to 6000 with a clock
divider of 25, which gives the 999.8 Hz from Section 2.5, and every wrap triggers <code>on_pwm_wrap()</code>. Max duty is
6000 (100%). We used a 4500 cap during early tuning and went back to 6000 once we added the ramp limit in Section 3.5.</p>
<p><b>IMU.</b> The MPU-6050 is on I2C0 at 400 kHz (SDA GPIO 8, SCL GPIO 9), powered from the Pico's 3.3 V, and set up as
in <a>[[t:regs]]</a>. The reads inside the ISR have 250 &micro;s timeouts, so a glitch can cost one sample but can't freeze
the loop. At start-up we fill the filters with the first reading, so the angle starts out right instead of slowly
climbing from 0.</p>
<table class="t" data-tab="regs"><tr><th>Register</th><th>Value</th><th>What it does</th></tr>
<tr><td>0x6B PWR_MGMT_1</td><td>0x00</td><td>Wake up</td></tr>
<tr><td>0x19 SMPLRT_DIV</td><td>7</td><td>8 kHz / 8 = 1 kHz sample rate, same as our loop</td></tr>
<tr><td>0x1B GYRO_CONFIG</td><td>0x00</td><td>&plusmn;250 &deg;/s (131 counts per &deg;/s)</td></tr>
<tr><td>0x1C ACCEL_CONFIG</td><td>0x00</td><td>&plusmn;2 g (16,384 counts per g)</td></tr>
<tr><td>0x37 / 0x38</td><td>0x10 / 0x01</td><td>Data-ready interrupt on (we don't use the pin; the PWM ISR polls instead)</td></tr>
<tr><td>0x3B / 0x43</td><td>read 6 bytes each</td><td>Accelerometer x, y, z and gyro x, y, z</td></tr>
</table>
<div class="tcap"><b>[[tn:regs]]</b> MPU-6050 registers used by <code>mpu6050.c</code>.</div>

<h2>3.4 &nbsp;The control loop</h2>
<p>Everything time-critical happens in <code>on_pwm_wrap()</code> on core 0, once every millisecond:</p>
<ol>
<li>Clear the interrupt and toggle GPIO 14 (so we can check the timing on a scope).</li>
<li>Read the IMU.</li>
<li>Smooth a<sub>x</sub> and a<sub>z</sub> and get the accelerometer angle with <code>atan2</code>.</li>
<li>Update the complementary filter with gyro y.</li>
<li>Check the demo button and step the target if it's time (Section 3.6).</li>
<li>If the loop is on, run PID; if not, reset the I term.</li>
<li>Update the PWM level if it changed.</li>
<li>Every 10th time, save the angle and duty for the screen.</li>
</ol>
<p>Here's the controller part, straight from <code>imu_demo.c</code> (comments shortened):</p>
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
<p>Positive error means the arm is too low and needs more thrust. D is subtracted because a fast-rising arm should get
<i>less</i> thrust, and a fast-falling arm should get more.</p>

<h2>3.5 &nbsp;Overcurrent protection and windup</h2>
<p>When the target jumps, the P term jumps too (80 &times; 90&deg; = 7200 counts when the arm is let go from hanging).
Slamming a stopped motor from 0 to full voltage pulls a big surge of current, because it isn't spinning yet so nothing
limits the current except the coil's resistance. So the final code lets the command <i>go up</i> by at most 20 counts per
millisecond. Going down isn't limited, so the controller can still cut thrust instantly.</p>
{{eq:ulim}}
<p>You can see this ramp in every step in Section 5.2, as a dotted line going up in the duty plot. 300 ms is short
compared to the arm's roughly 1 s response, so it barely slows things down.</p>
<p>The ramp creates a new windup problem: while the output is stuck at the ramp limit, the error stays big and I would
keep growing. So we only let I grow when the output isn't already at the limit. This is the "clamping" fix from the
course PID notes, and it's why <code>i_max</code> could stay at 10000 (above the 6000 max output) and never kick in. I is
also kept at 0 or above, since negative I would only delay thrust.</p>

<h2>3.6 &nbsp;Demo button</h2>
<p>The button is on GPIO 15, wired to ground with the internal pull-up (pressed = low). The ISR checks it every 1 ms and
only believes a change after it's held for 20 checks in a row (20 ms debounce). Since each ISR call is 1 ms, we time the
demo by counting calls:</p>
<table class="t" data-tab="demo"><tr><th style="width:22%">When</th><th>What happens</th></tr>
<tr><td>Button held</td><td>Loop off, motor off, I reset, target &minus;90&deg;: the arm hangs straight down</td></tr>
<tr><td>Released, t = 0</td><td>Loop on, target 0&deg; (level)</td></tr>
<tr><td>t = 5 s</td><td>Target +30&deg;</td></tr>
<tr><td>t = 10 s</td><td>Target &minus;30&deg;</td></tr>
<tr><td>t = 15 s</td><td>Target 0&deg;; the sequence ends and the arm stays level</td></tr>
</table>
<div class="tcap"><b>[[tn:demo]]</b> Demo sequence. It uses whatever gains are loaded, with no reset needed.</div>
<p>The target only gets set at those four moments, so a serial <code>a</code> command can still change it in between.</p>

<h2>3.7 &nbsp;VGA display and serial commands</h2>
<p>The Pico drives the monitor through the adapter board we soldered in Lab 2 (<a>[[f:vgapcb]]</a>). We reused the
course's VGA driver (<a>[[f:dma]]</a>): three PIO state machines make the sync and colour signals, and DMA streams the
pixels to them, so the CPU doesn't have to. Core 1 does nothing but draw, so drawing can never slow down the control loop.</p>
<div class="two">
<figure data-fig="vgapcb"><img src="figures/vga_pcb.png" style="width:52%">
<figcaption><b>[[fn:vgapcb]]</b> Our VGA adapter board (from Lab 2).</figcaption></figure>
<figure data-fig="dma"><img src="figures/vga_dma.png" style="width:100%">
<figcaption><b>[[fn:dma]]</b> The VGA driver's DMA chain, from lecture.</figcaption></figure>
</div>
<ul>
<li><b>Top plot:</b> the filtered angle (yellow) and the target (light blue), &minus;90&deg; to +90&deg;.</li>
<li><b>Bottom plot:</b> the motor command <code>control</code>, 0 to 6000.</li>
<li><b>Text:</b> both angles, target, the three gains, duty, mode, I max and the live I term.</li>
</ul>
<p>One point is saved every 10 ms, so the screen shows the last 5.3 s. Note: we plot the raw controller output, not a
smoothed copy like the handout asks for. With D = 12 and the ramp limit it was smooth enough to read (Section 5.2), and
adding the course's one-line smoothing filter (<code>motor_disp</code>) is on our "would change" list (Section 6).</p>
<p><b>Serial commands.</b> Type a letter, then a value. The value goes straight into the variables the ISR reads, so it
takes effect within 1 ms.</p>
<table class="t" data-tab="serial"><tr><th>Cmd</th><th>Sets</th><th>Units / range</th></tr>
<tr><td><code>a</code></td><td>Target angle</td><td>&minus;90 to +90&deg; (0 = level)</td></tr>
<tr><td><code>p</code></td><td>K<sub>p</sub></td><td>duty counts per degree, 0&ndash;6000</td></tr>
<tr><td><code>i</code></td><td>K<sub>i</sub></td><td>duty counts per degree per ms, 0&ndash;100 (0 also resets I)</td></tr>
<tr><td><code>d</code></td><td>K<sub>d</sub></td><td>duty counts per &deg;/s, 0&ndash;6000</td></tr>
<tr><td><code>m</code></td><td>I cap <code>i_max</code></td><td>0&ndash;6000 duty counts</td></tr>
<tr><td><code>c</code></td><td>Loop on / off</td><td>1 / 0 (0 also turns the motor off)</td></tr>
<tr><td><code>n</code></td><td>Manual duty (turns the loop off)</td><td>0&ndash;6000</td></tr>
<tr><td><code>t</code></td><td>Plot speed</td><td>ISR calls per plotted point (default 10)</td></tr>
</table>
<div class="tcap"><b>[[tn:serial]]</b> Serial commands.</div>

<h2>3.8 &nbsp;Wiring</h2>
<table class="t" data-tab="wiring"><tr><th>Signal</th><th>Pico pin</th><th>Notes</th></tr>
<tr><td>VGA Hsync / Vsync</td><td>GPIO 16 / 17</td><td>PIO state machines</td></tr>
<tr><td>VGA Green lo / Green hi / Blue / Red</td><td>GPIO 18 / 19 / 20 / 21</td><td>470 &Omega; / 330 &Omega; / 330 &Omega; / 330 &Omega;</td></tr>
<tr><td>MPU-6050 SDA / SCL</td><td>GPIO 8 / 9</td><td>I2C0, 400 kHz; IMU powered from 3.3 V</td></tr>
<tr><td>Motor PWM</td><td>GPIO 4</td><td>Slice 2 channel A, to the 4N35 through 330 &Omega;</td></tr>
<tr><td>(PWM slice 2 B)</td><td>GPIO 5</td><td>Set to 0, unused</td></tr>
<tr><td>ISR timing</td><td>GPIO 14</td><td>Toggles every ISR (for the scope)</td></tr>
<tr><td>Demo button</td><td>GPIO 15</td><td>To GND, internal pull-up, 20 ms debounce</td></tr>
</table>
<div class="tcap"><b>[[tn:wiring]]</b> Pico wiring.</div>
<figure data-fig="pinout"><img src="figures/pinout.svg" style="width:96%">
<figcaption><b>[[fn:pinout]]</b> Pico 2 pinout with our pins, coloured by subsystem.</figcaption></figure>
<figure data-fig="block"><img src="figures/system_block.svg" style="width:100%">
<figcaption><b>[[fn:block]]</b> System block diagram. Core 0 runs the 1 kHz control loop and the serial thread; core 1
only draws. The orange path is the physical feedback through the arm.</figcaption></figure>

<!-- ======================================================= 4 DOCUMENTATION -->
<h1 class="sec">4 &nbsp;Documentation</h1>
<p>Where to find the drawings, code and data the course policy asks for:</p>
<table class="t" data-tab="docs"><tr><th>Item</th><th>Where</th></tr>
<tr><td>Motor circuit schematic</td><td><a>[[f:schematic]]</a>, Section 3.2</td></tr>
<tr><td>System block diagram</td><td><a>[[f:block]]</a></td></tr>
<tr><td>Pinout and wiring</td><td><a>[[f:pinout]]</a>, <a>[[t:wiring]]</a></td></tr>
<tr><td>Complementary filter</td><td><a>[[f:angles]]</a>, <a>[[f:compblock]]</a>, Section 2.2</td></tr>
<tr><td>IMU registers, serial commands, demo timing</td><td><a>[[t:regs]]</a>, <a>[[t:serial]]</a>, <a>[[t:demo]]</a></td></tr>
<tr><td>VGA adapter and driver</td><td><a>[[f:vgapcb]]</a>, <a>[[f:dma]]</a></td></tr>
<tr><td>Photos of the rig</td><td><a>[[f:rig]]</a> and the photos in <a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a></td></tr>
<tr><td>VGA screenshots (demo)</td><td><a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a>; earlier runs in <a>[[f:ponly]]</a>, <a>[[f:accelnoise]]</a></td></tr>
<tr><td>Settling times, hover duties</td><td><a>[[t:settle]]</a>, <a>[[t:hover]]</a></td></tr>
<tr><td>Commented code</td><td>Appendix A</td></tr>
<tr><td>AI prompt log</td><td>Appendix B</td></tr>
</table>
<div class="tcap"><b>[[tn:docs]]</b> Documentation index.</div>

<!-- ======================================================= 5 RESULTS -->
<h1 class="sec">5 &nbsp;Results</h1>
<h2>5.1 &nbsp;Final gains</h2>
<p>K<sub>p</sub> = 80, K<sub>i</sub> = 0.2, K<sub>d</sub> = 12, <code>i_max</code> = 10000 (never reached), output 0&ndash;6000
with a ramp limit of +20 counts per ms. One set of gains ran the whole demo with no reset. Section 7 (Q3) explains how
we picked them.</p>

<h2>5.2 &nbsp;Demo sequence</h2>
<p><a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a> show the four steps of the demo, taken from our video of the checked-off run.
Each VGA screen (left) is paired with a photo of the arm at that angle (right). On every screen, the top plot is the
angle (yellow) vs. the target (blue), the bottom plot is the motor command (0&ndash;6000), and the newest data is on
the right.</p>

<figure data-fig="demo1"><div class="pair"><img src="figures/zero.png"><img class="ph" src="figures/1D_zero.png"></div>
<figcaption><b>[[fn:demo1]]</b> <b>t = 0: let go, &minus;90&deg; &rarr; 0&deg;.</b> The duty starts at 0 (motor off while the
button is held), ramps up (the dotted rise) to about 4100, dips to about 1300 as D brakes the rising arm, then settles at
3278. No overshoot; I pulls in the last few degrees. At the end: angle &minus;0.8&deg;, duty 3278, I term 3278.5, so I is
basically the whole command, as Section 2.4 says. Right: the arm level (seen edge-on), fan hanging below.</figcaption></figure>

<figure data-fig="demo2"><div class="pair"><img src="figures/positive_30.png"><img class="ph" src="figures/1d_positive_30.png"></div>
<figcaption><b>[[fn:demo2]]</b> <b>t = 5 s: 0&deg; &rarr; +30&deg;.</b> P kicks in (80 &times; 30&deg; = 2400 extra counts) and the
duty ramps up to about 5800. The arm overshoots to about +46&deg;, the duty dips to about 3100 while the extra I built up
on the way up drains off, and then it settles at +30.0&deg; with duty 3383 and I term 3336.5. Right: the arm at +30&deg;.</figcaption></figure>

<figure data-fig="demo3"><div class="pair"><img src="figures/negative_30.png"><img class="ph" src="figures/1D_negative_30.png"></div>
<figcaption><b>[[fn:demo3]]</b> <b>t = 10 s: +30&deg; &rarr; &minus;30&deg;.</b> The command drops straight to 0. The fan can't pull
down, so gravity does the work. The arm falls past the target, P and D ask for about 5000 counts to catch it, and it still dips to about
&minus;56&deg; and bounces once. I drained during the fall, so the end is a slow creep: duty 2533 and still climbing
(I term 2433.9), arm at &minus;32.8&deg;. Right: the arm at &minus;30&deg;.</figcaption></figure>

<figure data-fig="demo4"><div class="pair"><img src="figures/zero_again.png"><img class="ph" src="figures/1D_zero.png"></div>
<figcaption><b>[[fn:demo4]]</b> <b>t = 15 s: &minus;30&deg; &rarr; 0&deg;.</b> The fastest step. I is already close to what
it needs for level, so a short P kick (duty about 4700) lifts the arm with only about 4&deg; of overshoot. It settles at
0.2&deg; with duty 3288 and I term 3307.2. Right: the arm back at level (same pose as <a>[[f:demo1]]</a>).</figcaption></figure>

<h2>5.3 &nbsp;Settling times</h2>
<table class="t" data-tab="settle"><tr><th>Step</th><th>Settling time (s)</th><th>Overshoot (from screen)</th><th>What slowed it down</th></tr>
<tr><td>&minus;90&deg; &rarr; 0&deg;</td><td>2.74</td><td>none (comes up from below)</td><td>I starts at 0 and has to build up the hover command</td></tr>
<tr><td>0&deg; &rarr; +30&deg;</td><td>2.38</td><td>&asymp; 16&deg; (peak &asymp; +46&deg;)</td><td>Extra I from the climb has to drain off</td></tr>
<tr><td>+30&deg; &rarr; &minus;30&deg;</td><td>3.56</td><td>&asymp; 26&deg; (low &asymp; &minus;56&deg;)</td><td>Gravity-driven fall (fan can't pull down); I has to rebuild</td></tr>
<tr><td>&minus;30&deg; &rarr; 0&deg;</td><td>0.98</td><td>&asymp; 4&deg;</td><td>I already close to the right value</td></tr>
</table>
<div class="tcap"><b>[[tn:settle]]</b> Settling times measured from our video of the demo. Overshoot was read off the VGA
screenshots (1.2&deg; per pixel, so about &plusmn;3&deg;).</div>
<p>The pattern makes sense. Going up, the fan pushes and gravity and D brake, so it's well controlled. Going down,
gravity does the pushing and only the fan can brake, and it has to ramp back up from zero first, so that step overshoots
the most and takes the longest. In every step, how long the tail lasts depends on how far the I term has to move to
reach the new hover value.</p>

<h2>5.4 &nbsp;Hover duty vs. angle</h2>
<p>Once the arm is settled, P and D are about zero, so the duty tells us how much thrust each angle needs.</p>
<table class="t" data-tab="hover"><tr><th>Angle</th><th>Duty (I term)</th><th>Duty as % of period</th>
<th>(duty / duty<sub>0&deg;</sub>)&sup2; &asymp; thrust ratio</th><th>Simple-arm prediction cos &phi;</th></tr>
<tr><td>0&deg;</td><td>3278 (3279)</td><td>54.6%</td><td>1.00</td><td>1.00</td></tr>
<tr><td>+30&deg;</td><td>3383 (3337)</td><td>56.4%</td><td>1.07</td><td>0.87</td></tr>
<tr><td>&minus;30&deg;</td><td>2533 (2434), still rising</td><td>42.2%</td><td>&le; 0.60</td><td>0.87</td></tr>
</table>
<div class="tcap"><b>[[tn:hover]]</b> Settled duty at each demo angle, from the VGA readouts. The thrust ratio assumes
thrust &prop; &omega;&sup2; and fan speed roughly &prop; average voltage.</div>
<p>A simple arm would need the same thrust at &plusmn;30&deg;. Ours needs <i>more</i> at +30&deg; and a lot less at
&minus;30&deg;, because the fan hangs below the arm (Section 2.3). Fitting our numbers gives d/r &asymp; 0.4&ndash;0.5. That's
rough (the &minus;30&deg; duty was still creeping up), but the direction is clear. It also puts the arm's tipping point
around 20&ndash;30&deg; above level instead of exactly at level.</p>

<h2>5.5 &nbsp;Stable range</h2>
<p>With the final gains, the arm was stable from <b>&minus;90&deg;</b> (hanging; the controller just turns the fan off) up to
about <b>+50&deg;</b>. The top limit changed depending on which 5 V motor supply we used; above it, the arm wasn't stable with
these gains (more in Section 7, Q4).</p>

<h2>5.6 &nbsp;Earlier tuning runs</h2>
<div class="two">
<figure data-fig="ponly"><img src="figures/p_only_kp120.png" style="width:100%">
<figcaption><b>[[fn:ponly]]</b> Early P-only test (K<sub>p</sub> = 120, no I or D, target 0&deg;) on an older build with a
&plusmn;250 angle axis. The arm oscillates steadily, about 6.5 cycles in 5.3 s (&asymp; 1.2 Hz): right at the edge of stable.
The I term still showed 3000 from an earlier run, because back then setting K<sub>i</sub> = 0 didn't reset it. The
final code does reset it.</figcaption></figure>
<figure data-fig="accelnoise"><img src="figures/early_accel_noise.jpg" style="width:100%">
<figcaption><b>[[fn:accelnoise]]</b> Early build with much bigger gains (K<sub>p</sub> = 500, K<sub>d</sub> = 300,
K<sub>i</sub> = 5). The bottom plot showed the raw accelerometer (&plusmn;2 g): with the fan on, vibration spreads it across
most of the range, while the filtered angle on top is a clean line. This is why we need the complementary filter.</figcaption></figure>
</div>

<!-- ======================================================= 6 CONCLUSION -->
<h1 class="sec">6 &nbsp;Conclusion</h1>
<p>Our helicopter did everything the lab asked for. It ran the full 0&deg; / +30&deg; / &minus;30&deg; / 0&deg; demo on one
set of gains with no reset, every step settled within 3.6 s, we could change the gains and target from the serial
terminal at any time, and the VGA showed the angle, target and motor command live.</p>
<p>The results also matched the theory. The complementary filter kept fan vibration out of the angle. Once settled, the
I term equalled the hover duty, like PID theory says it should. And the lopsided settling times and hover duties are
what you'd expect from a fan that can only push up and an arm whose weight hangs off-centre.</p>
<p><b>What we'd change next time:</b></p>
<ul>
<li>Plot a smoothed copy of the motor command (<code>motor_disp</code>) like the handout asks, instead of the raw one.</li>
<li>Measure the gyro's built-in error at start-up (average a second of readings with the arm still) and subtract it.</li>
<li>Add a "feed-forward" guess of the hover thrust using the r cos &phi; + d sin &phi; model, so I only has to fix what's
left. That should shorten the slow tails, especially after going down.</li>
<li>Move the <code>printf</code> for button presses out of the ISR, since printing inside the 1 kHz interrupt can make one
loop run long.</li>
<li>Measure the arm's length and mass so we can check the model with real numbers.</li>
</ul>

<!-- ======================================================= 7 QUESTIONS -->
<h1 class="sec">7 &nbsp;Answers to the Lab Report Questions</h1>
<p>The helicopter handout asks the report to include the following.</p>

<div class="q"><h3>Q1. A schematic of the circuit you built</h3>
<p>See <a>[[f:schematic]]</a>, plus <a>[[t:wiring]]</a>, <a>[[f:pinout]]</a> and <a>[[f:block]]</a>. GPIO 4 (PWM) lights the
4N35's LED through 330 &Omega;. The 4N35 switches the 12 V gate supply (through a kill switch) onto the IRLB8721 MOSFET's
gate, with a 10 k&Omega; pull-down on the gate and a 1 M&Omega; resistor to help it switch off fast. The motor runs from a
separate 5 V supply with a 1N4001 diode and a 0.1 &micro;F capacitor across it. The Pico and motor sides share no ground.
The IMU (GPIO 8/9), VGA (GPIO 16&ndash;21) and button (GPIO 15) are wired as in <a>[[t:wiring]]</a>.</p></div>

<div class="q"><h3>Q2. VGA screen dumps of (1) motor control and (2) actual angle, including the four-angle demo</h3>
<p>See <a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a>, one for each demo step (0&deg;, +30&deg;, &minus;30&deg;, 0&deg;), each next to a
photo of the arm at that angle. The top trace is the angle vs. the target; the bottom trace is the motor command
(0&ndash;6000). While the button is held, the command is 0 and the arm hangs at &minus;90&deg; (left edge of
<a>[[f:demo1]]</a>). Every step shows the ramp-limited rise in the command, and the settled command matches the I term.</p></div>

<div class="q"><h3>Q3. How you selected the three PID gains</h3>
<p><b>Ballpark from units.</b> We picked starting values so each term would give a reasonable duty count:</p>
<ul>
<li>K<sub>p</sub>: a 90&deg; error (hanging, target level) should ask for about full power, so K<sub>p</sub> &asymp; 6000/90
&asymp; 67. So: tens.</li>
<li>K<sub>d</sub>: the gyro rate in &deg;/s is about the same size as the error in degrees, so K<sub>d</sub> is also tens.
(The course page's "thousands" assumes taking differences of noisy samples, not a gyro.)</li>
<li>K<sub>i</sub>: I adds K<sub>i</sub>&middot;e a thousand times a second, so K<sub>i</sub> has to be much smaller. We
started near 1/32.</li>
</ul>
<p><b>Tuning steps</b> (the order from lecture and the PID notes):</p>
<ol>
<li><b>P only:</b> turn up K<sub>p</sub> until you find the edge between "wobbles die out" and "wobbles grow." K<sub>p</sub> =
120 oscillated steadily at about 1.2 Hz (<a>[[f:ponly]]</a>), so we backed off to 80, about two-thirds of that.</li>
<li><b>Add D</b> until the wobbling stops. Our test: push the arm down below the target and let go. It should spring
back, overshoot once, and settle quickly. We ended at K<sub>d</sub> = 12.</li>
<li><b>Add I</b> to get rid of the leftover error and bring the arm onto the target. More I gets there faster but
overshoots and wobbles slowly. We settled on K<sub>i</sub> = 0.2. At that rate a 5&deg; error grows I by 1000 counts per
second, enough to build the roughly 3300-count hover command in a few seconds.</li>
<li><b>Run the whole demo</b> with the button and adjust. The windup fix (Section 3.5) handled the rest, so we left
<code>i_max</code> at 10000.</li>
</ol>
<p>The live I-term readout on the VGA was our most useful tuning tool: once the arm settles, it should equal the duty,
which tells you P and D are done and only I is holding the arm up (<a>[[f:demo1]]</a>&ndash;<a>[[f:demo4]]</a>).</p></div>

<div class="q"><h3>Q4. What are the maximum/minimum angles that produce stable behaviour for your PID gains?</h3>
<p><b>Max &asymp; +50&deg;, min &minus;90&deg;</b> (0&deg; = level). The max depended on which 5 V motor supply we used. Why there's
a limit:</p>
<ul>
<li><b>Min:</b> &minus;90&deg; is just hanging. Near there the thrust needed drops to zero, the output sits at 0 and gravity
holds the arm, so it's stable for free.</li>
<li><b>Max:</b> above the arm's tipping point (level for a simple arm, a bit higher for ours, Section 5.4), gravity pushes
the arm further away instead of back. The higher you go, the stronger that push, until D can't keep up.</li>
<li><b>The plant changes with angle:</b> how much the arm responds to one duty count depends on fan speed, and our gains
were tuned for the demo range near level.</li>
<li><b>The supply matters:</b> a different supply changes thrust per duty count (thrust &prop; V&sup2;), which scales the whole
loop. The same gains end up closer to or further from the edge, so the max angle moved.</li>
</ul></div>

<div class="q"><h3>Q5. What are the settling times at different angles?</h3>
<table class="t"><tr><th>Step</th><th>Settling time</th><th>Overshoot</th></tr>
<tr><td>&minus;90&deg; &rarr; 0&deg; (let go)</td><td>2.74 s</td><td>none</td></tr>
<tr><td>0&deg; &rarr; +30&deg;</td><td>2.38 s</td><td>&asymp; 16&deg;</td></tr>
<tr><td>+30&deg; &rarr; &minus;30&deg;</td><td>3.56 s</td><td>&asymp; 26&deg;</td></tr>
<tr><td>&minus;30&deg; &rarr; 0&deg;</td><td>0.98 s</td><td>&asymp; 4&deg;</td></tr></table>
<p style="margin-top:5pt">(Same data as <a>[[t:settle]]</a>.) Going up takes about 1&ndash;2.7 s. Going down is slowest
(3.56 s) because the fan can only cut thrust: gravity drives the fall, the arm dips past the target, and I has to rebuild.
The fastest step started with I already near the right value; the slowest upward step (letting go from &minus;90&deg;)
started with I at zero.</p></div>

<div class="q"><h3>Q6. A heavily commented listing of your code</h3>
<p>Appendix A lists <code>imu_demo.c</code>, <code>mpu6050.c</code>, <code>mpu6050.h</code> and <code>CMakeLists.txt</code>
exactly as we demoed them. The course VGA driver and protothreads header weren't changed, so they aren't listed. Every
change from the course MPU-6050 demo is marked in the comments (<code>ADDED</code>, <code>CHANGED</code>, <code>FIXED</code>,
<code>REMOVED</code>) and shaded in the listing.</p></div>

<div class="q"><h3>Q7. A prompt log from any AI tool used for code generation</h3>
<p>Appendix B has the full log of our coding sessions with Claude Code (model: Claude Opus 5.5): 18 prompts from
Oct 21&ndash;22, 2026, with our prompts word for word and Claude's responses. Totals: {{TOT_PW}} prompt words,
{{TOT_RW}} response words and {{TOT_CL}} lines of code given. Suggested additions / deletions / changes:
<b>{{TOT_S}}</b>. Accepted (still in the final code): <b>{{TOT_A}}</b>.</p></div>

<!-- ======================================================= 8 WORK / AI -->
<h1 class="sec" style="break-before:auto; margin-top: 18pt">8 &nbsp;Work Distribution and AI Use</h1>
<p>Amber, Ivan, and Zarif worked together on all parts of the lab. We often met outside of our lab section, and most of
the work was done together in the lab. Outside the lab, we kept in touch so everyone knew what was done and what was next.</p>
<p><b>AI use.</b> We used Claude Code (Claude Opus 5.5) while writing the program. Every prompt and response is in
Appendix B, and the code it contributed is marked with <code>ADDED</code> / <code>CHANGED</code> / <code>FIXED</code> comments
(shaded in Appendix A). We also used Claude to help organise, typeset and edit this report from our notes, draft report,
photos, screenshots and measurements. Code it suggested while writing the report (a smoothed display variable, a
different button routine on GPIO 2, and extra comments) was not added to our program. All measurements, photos,
screenshots and hardware are ours.</p>

<h1 class="sec">References</h1>
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
<p>These are the files exactly as we built and demoed them (Pico 2 / RP2350, Pico SDK 2.3.1). The program also uses the
course's VGA driver (<code>VGA/vga16_graphics_v3.c/.h</code> and its three PIO programs) and
<code>pt_cornell_rp2040_v1_4.h</code>, unchanged. Changes from the course MPU-6050 demo are marked in the comments with
<code>ADDED</code>, <code>CHANGED</code>, <code>FIXED</code> or <code>REMOVED</code>. Those are the parts written with AI help
(Appendix B) and later edited by us. <span class="legend"></span> marks those lines. Comments are green.</p>
{{CODE}}

<!-- ======================================================= APPENDIX B -->
<h1 class="sec">Appendix B &nbsp;AI Prompt Log</h1>
<p><b>Tool:</b> Claude Code in VS Code, model <b>Claude Opus 5.5</b>. <b>Dates:</b> October 21&ndash;22, 2026.
<b>Source:</b> the prompt log Claude kept in our project (<code>MPU6050_IMU_Demo/PROMPT_LOG.md</code>), copied below.
Prompts are word for word, typos included. Claude kept the log as it went (from prompt 9 on, filling in 1&ndash;8
afterwards), so some responses are shorter summaries of the full chat reply.</p>
<p><b>How we counted.</b> <i>Words</i> are counted from the log (our prompt, and Claude's response without code).
<i>Code lines given</i> counts the C lines in each response. One <i>suggested</i> addition, deletion or change is one
distinct change to the program (like a new serial command or one edited line), not one line of text. <i>Accepted</i>
means it's still in the final <code>imu_demo.c</code> (Appendix A), even if we edited it later. Things we used and then
removed count as not accepted.</p>
{{LOG_TABLE}}
<div class="tcap" style="margin-top:4pt"><b>Table B1.</b> Prompt log summary (18 prompts). Totals: suggested {{TOT_S}}, accepted {{TOT_A}}
(additions / deletions / changes).</div>
<p style="font-size:9.4pt"><i>Note:</i> the demo-button sequence and the overcurrent protection (ramp limit and the windup
fix) are also marked <code>ADDED</code> in Appendix A, but they were written after the last entry in
<code>PROMPT_LOG.md</code>, so they aren't in the log or counted in Table B1.</p>
<h2>Full log</h2>
{{LOG_ENTRIES}}
"""
