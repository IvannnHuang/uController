# AI Prompt Log: ECE 5730 Lab 3 Report (1D Helicopter)

**Tool:** Claude (claude.ai, "MicroControllers" project)
**Dates:** October 28, 2026 (prompts 1–8) and November 8, 2026 (prompt 9)
**Report written in:** [ECE 5730 Lab 3 Report: PID Control of a 1D Helicopter](https://claude.ai/artifact/CKuCRfTtZA97pxoeaNnbNt)

Prompts are quoted verbatim, typos included. "Words" counts only the words we typed, not pasted code, attached files or images.

---

## Summary

| # | Time | Prompt (summary) | Attachments | Words | Code changes suggested (add / delete / modify) | Accepted |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | Oct 28, 3:06 pm | Here is the current report; add details and pictures; check the code | Report text, 7 course-page PDFs | 50 | 0 / 0 / 0 (report only) | n/a |
| 2 | Oct 28, 3:12 pm | Here is our code so far, plus the code it was based on | imu_demo.c, PWM demo, mpu6050.c | 31 | 7 / 0 / 3 | [fill in] |
| 3 | Oct 28, 3:14 pm | Pictures of the rig and screen | 2 photos | 7 | 0 / 0 / 0 | n/a |
| 4 | Oct 28, 3:19 pm | Add more from the PDFs; answer the handout's report questions; do we need scope pictures? | Handout's report requirements (pasted) | 33 typed + 124 pasted | 9 / 0 / 2 (comments only) | [fill in] |
| 5 | Oct 28, 3:20 pm | Answer the questions explicitly at the end, like an analysis section | none | 12 | 0 / 0 / 0 | n/a |
| 6 | Oct 28, 3:35 pm | Make it less verbose; add more photos | 9 course-page figures | 8 | 0 / 0 / 0 | n/a |
| 7 | Oct 28, 3:40 pm | Add info and images from our draft report | Draft report PDF | 22 | 0 / 0 / 0 | n/a |
| 8 | Oct 28, 3:46 pm | Typeset all formulas as images | none | 20 | 0 / 0 / 0 | n/a |
| 9 | Nov 8, 1:17 pm | Make a markdown log of these prompts, with all links and PDFs | none | 27 | 0 / 0 / 0 | n/a |

**Code totals:** 16 additions, 0 deletions and 5 modifications suggested. 9 of the additions and 2 of the modifications were comments only. Fill in the "Accepted" column with what we kept in our final code.

---

## Source material we gave Claude

### Course-page PDFs (prompt 1)

We saved each course web page as a PDF and attached it.

| PDF we attached | Pages | Original page |
| --- | --- | --- |
| Helicopter.pdf | 8 | [PID control of a 1D helicopter (lab handout)](https://vanhunteradams.com/Pico/Helicopter/Helicopter.html) |
| Complementary_Filters.pdf | 8 | [Complementary filters](https://vanhunteradams.com/Pico/ReactionWheel/Complementary_Filters.html) |
| PID.pdf | 17 | [Phenomenological introduction to PID controllers](https://vanhunteradams.com/PID/PID.html) |
| PID_Analytical-Copy1.pdf | 24 | [Analytical introduction to PID controllers](https://vanhunteradams.com/PID/PID_Analytical.html) |
| MotorCircuit.pdf | 9 | [DC motor circuit and PWM](https://vanhunteradams.com/Pico/Helicopter/MotorCircuit.html) |
| Display.pdf | 5 | [Data display](https://vanhunteradams.com/Pico/Helicopter/Display.html) |
| I2C.pdf | 15 | [Inter-Integrated Circuit (I2C)](https://vanhunteradams.com/Protocols/I2C/I2C.html) |

### Other links and files

- **Course policy page** (pasted in prompt 4): [ECE 4760/5730 course policy](https://people.ece.cornell.edu/land/courses/ece4760/EE4760_policy.html), which lists the required report sections.
- **Course demo code** (linked from the handout; Claude used it to check our header and build file): [MPU6050 IMU demo](https://github.com/vha3/Hunter-Adams-RP2040-Demos/tree/master/Sensors/MPU6050_IMU_Demo) and [PWM demo](https://github.com/vha3/Hunter-Adams-RP2040-Demos/tree/master/PWM/PWM_Demo).
- **Our files:** the report text (prompt 1), imu_demo.c and mpu6050.c (prompt 2), and our earlier draft, ECE_5730_Lab_Report_3.pdf (prompt 7).
- **Images:** 2 photos of the rig and VGA screen (prompt 3) and 9 figures from the course pages (prompt 6).

---

## 1. Starting point: report, PDFs and code

**Prompt:**
> here is your current version of our lab report,
>
> I might need to add more details and more pictures so I will fed you them add them as you see fit. you will also have to check out code so far
>
> please extra photos as you see fit as well,

**Attachments:** the current report text and the 7 course-page PDFs listed above.

**Response:** Found the existing report doc and read the handout and motor circuit PDFs. Drew four figures and added them to the report:
- the motor driver schematic (4N35, IRLB8721, 1N4001, 0.1 µF, 330 Ω / 1 MΩ / 10 kΩ)
- the complementary filter block diagram
- the fix15 (15.16) bit layout
- the system block diagram

Also added a paragraph explaining the motor circuit and asked for our code, photos and measurements. No code changes.

---

## 2. Our code so far

**Prompt:**
> now here is. my code so far ima_demo.c is the file :
>
> and here is some other code that may be helpful or was worked off of to get us here:

**Attachments:** our imu_demo.c, plus the course PWM demo and mpu6050.c pasted in.

**Response:** Checked the code against the report. Pins, ISR steps, PID math, fixed-point constants and serial commands all matched. Two handout requirements were missing: a low-passed motor command on the display and the button-triggered demo. Claude added both, fixed two stale comments, and compiled the file against the Pico 2 SDK with no errors or warnings. It was not tested on hardware. The report was updated to match.

**Code changes suggested: 7 additions, 0 deletions, 3 modifications.**

Additions:
1. Pin list in the file header (GPIO 2 button, GPIO 14/15 scope pins)
2. `motor_disp` variable for the low-passed display value
3. Demo button `#define`s and state variables
4. Demo button debounce and timed target sequence in the ISR
5. `motor_disp` update in the ISR
6. Demo status line on the VGA readout
7. Button GPIO setup in `main()`

Modifications:
1. Plot buffer stores `motor_disp` instead of raw `control`
2. Comment `'k' = Kp` corrected to `'p' = Kp`
3. Comment "manual 'p'" corrected to "manual 'n'"

Low-passed display value (from the course Display page):
```c
// every ISR call
motor_disp = motor_disp + ((control - motor_disp) >> 4) ;
// when a point is plotted
duty_buf[head] = motor_disp ;   // was: control
```

Demo sequence in the ISR:
```c
if (!gpio_get(BUTTON_PIN)) { if (button_count < DEBOUNCE_MS) button_count++ ; }
else                       { if (button_count > 0)           button_count-- ; }
if (button_count == DEBOUNCE_MS) button_down = 1 ;
else if (button_count == 0)      button_down = 0 ;

if (button_down) {                       // held: motor off, arm hangs down
    demo_state = DEMO_HELD ; closed_loop = 0 ; control = 0 ;
}
else if (demo_state == DEMO_HELD) {      // released: t = 0, target 0 deg
    demo_state = DEMO_RUNNING ; demo_ms = 0 ;
    desired_angle = int2fix15(0) ; closed_loop = 1 ;
}
else if (demo_state == DEMO_RUNNING) {
    demo_ms++ ;
    if      (demo_ms ==  5000) desired_angle = int2fix15(30) ;
    else if (demo_ms == 10000) desired_angle = int2fix15(-30) ;
    else if (demo_ms == 15000) { desired_angle = int2fix15(0) ; demo_state = DEMO_IDLE ; }
}
```

---

## 3. Photos of the rig and screen

**Prompt:**
> some pictures of the rig and screen

**Attachments:** a top-down photo of the rig and a photo of the VGA screen during a P-only test.

**Response:** Labelled the rig photo (Pico 2, VGA PCB, motor driver PCB, hinge, IMU, arm, motor, clamp) and added it as Figure 1. Added the screen photo, which shows steady oscillation at Kp = 120, Ki = Kd = 0, as an example of P-only behavior. No code changes.

---

## 4. More from the PDFs, and the handout's report questions

**Prompt:**
> can you add more stuff from the PDFs? couture and details? idk if thi sis enough? also please ensure you address the specific question here :
>
> Lab report
> Your written lab report should include the sections mentioned on the [policy page](https://people.ece.cornell.edu/land/courses/ece4760/EE4760_policy.html), and:
>
> * A schematic of the circuit you built
> * VGA screen dumps of typical two-trace: (1) motor-control and (2) actual angle. Include the demo sequence of four angles, as shown below
> * How you selected the three PID gains.
> * What are the maximum/minimum angles that produce stable behavior for your PID gains?
> * What are the settling times at different angles?
> * A heavily commented listing of your code.
> * A prompt log from any AI tool that you used for code generation. The log should include words exchanged, number of code additions/deletions/modifications suggested, and number of code additions/deletions/modification accepted. The AI tool will generate this log for you if prompted to do so.
>
> also do I need any oscilloscope pictures?

**Response:** Read the policy page and the PID, analytical PID and I2C PDFs. Added to the report:
- the motor and arm models, and what each PID gain does
- a table of practical PID problems and our fixes
- I2C protocol details, the IMU registers and a timing estimate
- a Pico 2 pinout figure, a Documentation index and a References list
- the full code listing in Appendix A and this session's prompt log rows in Appendix B

Answer on scope pictures: not required, since the handout allows VGA instead. One shot of GPIO 14 would still show the 1 kHz loop timing.

**Code changes suggested: 9 additions and 2 modifications, all comments only**, so the code listing would count as heavily commented:
- Additions: a file overview, header comments on 6 functions, header comments and register notes on 2 driver functions, and fixed-point notes in mpu6050.h (including a note that the course's unused `divfix` macro has a precedence bug).
- Modifications: the `closed_loop` comment and the clock-setup comment.

---

## 5. Answer the questions as an analysis section

**Prompt:**
> liek explicitly answer these question at the end liek an analysis seciton

**Response:** Added an "Answers to Specific Lab Questions" section after the Conclusion, as the policy page requires. It has one subsection per question; blanks remain for measurements from the final demo. Also moved the duplicate gain-selection text out of Results. No code changes.

---

## 6. Less verbose, more photos

**Prompt:**
> make it less verbose, also add more photos:

**Attachments:** 9 figures from the course pages.

**Response:** Rewrote every section more concisely. Added 5 of the 9 figures, each credited to the course notes:
- the accelerometer and gyro angles, side by side
- the closed-loop block diagram
- the P and I error curves
- the forces on the arm
- integrator windup

Left out the upright-pendulum drawing (a different rig) and the course filter diagram, which duplicates ours. Renumbered all figures. No code changes.

---

## 7. Our earlier draft

**Prompt:**
> pleas also add in info from this current draft of the lab report, some section might not be useful, but images are

**Attachments:** ECE_5730_Lab_Report_3.pdf (our earlier draft).

**Response:** Added the VGA adapter PCB photo (cropped from the Lab 2 breadboard photo) and the VGA DMA chain slide. Also added the draft's VGA driver description: double buffering, about 16.7 ms per frame, and 640 × 480 × 4 bits in about 300 kB of SRAM. Left out material that was Lab 2 content or didn't fit:
- the 17.15 fix15 diagram (Lab 3 uses 15.16)
- the Lab 2 wiring table
- the official pinout (ours shows the same pins plus our assignments)
- the cover meme and the helicopter graphic

No code changes.

---

## 8. Formulas as images

**Prompt:**
> for all forumlas, please just make the math type ad paste in a screenshot of that formula into this report

**Response:** Typeset all 8 formulas with LaTeX and replaced each formula block with its image: complementary filter, accelerometer angle, PID law, de/dt = −ω, motor transfer function, arm torque balance, linearized arm, and PWM frequency. No code changes.

---

## 9. This log

**Prompt:**
> pleas make a markdown fo the prompts I gave you here to writ ethic report expsivalyl all fo the links and their PDFs I think I  made

**Response:** This file. No code changes.
