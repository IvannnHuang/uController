# AI Prompt Log: ECE 5730 Lab 3 Final Report (1D Helicopter)

**Tool:** Claude Code in VS Code, model Claude Opus 5.5
**Date:** November 8, 2026
**Team:** Amber Li, Ivan Huang, Zarif Karim (Thursday section)
**What this session did:** finished the Lab 3 report from our draft, the earlier claude.ai report and the course readings. It produced a detailed version and an easier-to-read version of the report, each as a PDF and a Word file.

Prompts are quoted verbatim, typos included. "Words" counts only the words we typed. No changes were made to the lab program (`MPU6050_IMU_Demo/`) in this session. All code Claude wrote here is report-building scripts.

---

## Summary

| # | Prompt (summary) | Words | Result | Changes to our lab code (add / delete / modify) |
| --- | --- | --- | --- | --- |
| 1 | Finish the report from our draft, the claude.ai report, the readings and the code. Add an AI prompt log appendix built only from `PROMPT_LOG.md`. Answer the handout's report questions. Pair the demo screenshots with the arm photos | 288 | Detailed report, `claude_report_final.pdf` (51 pages) | 0 / 0 / 0 |
| 2 | Write it more casually and less wordy, as a second copy | 27 | Plain-language report, `claude_report_simple.pdf` (49 pages) | 0 / 0 / 0 |
| 3 | Also make a Word document of the report | 10 | `claude_report_simple.docx` | 0 / 0 / 0 |
| 4 | Skip derivations; only keep final formulas used in the lab or needed for simple understanding | 24 | Plain-language report cut to 16 final formulas | 0 / 0 / 0 |
| 5 | "run it for me" (Word copy of the detailed report) | 4 | `claude_report_final.docx` | 0 / 0 / 0 |
| 6 | Which file has fewer derivations? | 6 | Answer: the `claude_report_simple` files | 0 / 0 / 0 |
| 7 | Organise the files into `final_report/` and write a markdown of this chat | 24 | This folder layout and this file | 0 / 0 / 0 |

**Totals:** 7 prompts, 383 words typed. 0 additions, 0 deletions and 0 modifications to our lab program.

---

## Source material used

| Source | Where it is now | Used for |
| --- | --- | --- |
| Our draft report (`official_report_11_8_26.pdf`) | `sources/drafts/` | Settling times, stable range (−90° to about +50°), tuning descriptions, work distribution, early photos |
| Earlier claude.ai report (`claude_report.pdf`) and its prompt log (`SESSION_LOG_Lab3_Report.md`) | `sources/drafts/` | Starting structure, figures from the course pages |
| Course readings: Helicopter, Complementary_Filters, PID, PID_Analytical-Copy1, MotorCircuit, Display, I2C | `sources/readings/` | Math and physics sections; the handout's report questions |
| VGA screenshots (`zero`, `positive_30`, `negative_30`, `zero_again`), arm photos (`1D_*`), demo videos | `sources/media/` | Demo figures, gains and readouts |
| Final code (`imu_demo.c`, `mpu6050.c/.h`, `CMakeLists.txt`) | `../MPU6050_IMU_Demo/` (not moved; tracked in git) | Appendix A, and every number in the report |
| `PROMPT_LOG.md` (our 18 coding prompts, Oct 21–22) | `../MPU6050_IMU_Demo/` (not moved) | Appendix B (the only source for it) |

---

## 1. Finish the report

> i've attached my current report so far the offocial report in the lab 3 folder. i've also attached some of your work in the claude_report for what i wanted to. now that i've officialy compelted the whole lab and checkoffs we should be good to write up the whole report
> you will find the /Users/zarifkarim/Documents/uCont/uController/Labs/Lab3 - PID Helicopter/MPU6050_IMU_Demo/PROMPT_LOG.md. using only this markdown you must also make an AI prompt log my own prompts and their according responses from yo calude i belvie i used opus 5.5 as the mdoel for these prompts. this will be it's own sction itn he appendix.
> i;'ve attach a markdown of how exalct i made the ogoriganl version of the cluade rpoert and also attached all fo the complientary readings needed to compelte this lab and lab report. i think the code should have alreayd been annotated with the according secitons that list exactly where AI was used to write our program so keep it like that.
> in the end i am asking you to touch up and finalize the claude report using al fo the inrfomraiton make sure everything is according ot the code we have as well, i am proedictini that most of th slab repsort is explainint and understa dh the math and physics behind PWM and PID controller adn stuffs. please ensuer you have a searte seciotn that answers the "Rlab report questions" as listed int he helicotper PDF
> I've alos featureed screnshots of the oscciloscope/ our screen to show the cycle occuring 0 -->+30 --> -30 --> 0 for the system reaching ot speciifa angles and maintining please do in clude that as well i think. these screenshots should also be put toegehter with their according 1d screenshots

**What Claude did:**
- Read all the sources above and checked every claim in the report against the final code.
- Rebuilt the report as HTML and rendered it to PDF with headless Chrome. It has sections 1–8, References and two appendices.
  - Formulas are typeset as images (matplotlib).
  - The pinout and system block diagrams were redrawn as SVG.
- **Corrections from the old claude.ai report:**
  - The button is on GPIO 15, not GPIO 2.
  - The duty limit is 6000, not 4500.
  - The ramp limit (+20 counts/ms) and conditional integration are now described.
  - All TODOs were replaced with real data.
- **Math and physics (Section 2):**
  - accelerometer vs. gyro
  - complementary filter
  - low-pass before `atan2`
  - motor and arm model, and hover thrust
  - PID terms, D from the gyro, and the gains in real units
  - practical PID problems
  - PWM frequency and average voltage
  - flyback diode
  - fixed point
  - I2C timing
- **Demo figures (Section 5.2):** each VGA screenshot is paired with its arm photo for 0° → +30° → −30° → 0°. Captions explain the duty trace. Gains and readouts were read off the screens: Kp 80, Ki 0.2, Kd 12.
- **Overshoot:** measured from the screenshots as ≈0°, 16°, 26° and 4° (about ±3°).
- **Hover duties:** the measured hover duties show the off-centre mass. Fitted d/r ≈ 0.4–0.5, a rough estimate.
- **Section 7:** answers all seven handout questions (Q1–Q7).
- **Appendix A:** the code listing, verbatim, with the ADDED / CHANGED / FIXED / REMOVED sections shaded.
- **Appendix B:** built only from `PROMPT_LOG.md`. It includes:
  - all 18 prompts verbatim, with the responses
  - word counts
  - suggested vs. accepted code changes: suggested 36 / 1 / 22, accepted 29 / 1 / 19
  - totals of 401 prompt words, 1719 response words and 214 code lines

**Things flagged for us to check:**
- The handout asks for a low-passed motor command on the screen, but our code plots the raw `control`. The report says so and lists the fix (`motor_disp`) as future work.
- The demo button and overcurrent protection are marked ADDED in the code but aren't in `PROMPT_LOG.md`. A note in Appendix B says so.
- "The contents of this report were written by us" was replaced with an AI-use statement.
- The cover date is 11.08.2026.
- Claims not supported by our notes were removed: testing each PID term alone, and the arm oscillating above 50°.

## 2. Easier language, less wordy

> can you write more colloquially, easier to read and dundersthad teh concepts at hand? make antoher copy ot the pdf with the easier language and less verbose

**What Claude did:** wrote a second copy of the report text (`content_simple.py`) with the same facts, figures and tables:
- shorter sentences, plain explanations and fewer subsections (2.1–2.6 and 3.1–3.8)
- built it with `python3 build_report.py simple`
- left the appendices unchanged, since the code and prompt log must stay verbatim

The body text came out about 13% shorter. The original report was left as it was.

## 3. Word document

> please alos make a word doc output of this report

**What Claude did:** wrote `make_docx.py`, which converts the built report HTML into a Word file with python-docx. It keeps:
- headings, figures, formulas (as images) and tables
- the boxed Q1–Q7 answers
- the shaded AI sections in the code listing
- the header ("Li_Huang_Karim_Thursday" and the course name) and page numbers

The file passes Word format validation. Only the first page could be previewed, because Word and LibreOffice aren't installed on this Mac.

## 4. Final formulas only

> i dont need derivations of equations really just need the final formuals they may have been sused soemwhere in this lab or simple undersatindg

**What Claude did:** removed the derivations from the plain-language report: transfer functions, the drift-offset proof, the de/dt step, and the PID zeros and time constants. Where the result matters, it's now one sentence.

16 formulas are kept:

| Group | Formulas |
| --- | --- |
| Used in the code | accelerometer angle, gyro step, complementary filter, ÷16 low-pass, PID law, per-ms PID update, gains in real units, ramp limit |
| Hardware numbers | PWM frequency, average motor voltage, fixed-point multiply, I2C read time |
| For understanding | arm torque balance, hover thrust, off-centre-mass torque, inductor voltage spike |

Rebuilt the PDF and the Word file.

## 5. Word copy of the detailed report

> run it for me

**What Claude did:** ran `make_docx.py full`, which produced `claude_report_final.docx` (all 25 formulas and the full derivations). It passes validation.

## 6. Which file has fewer derivations

> which file has the less derivations

**Answer:** the `claude_report_simple` files (PDF and Word) have only the 16 final formulas. The `claude_report_final` files are the detailed version, with all 25 equations and the derivations.

## 7. Organise files and write this log

> please orgnaize the assortment of files int ot he final_report folder or something, then make a markdown of what we did in this chat

**What Claude did:** moved every untracked report file into `final_report/` (layout below). It then updated the script paths and rebuilt all four outputs to confirm they still build: 51 and 49 pages, and both Word files pass validation.

`MPU6050_IMU_Demo/` and `PWM_Demo/` were not moved, because they are tracked in git. Nothing was committed.

---

## Folder layout

```
Lab3 - PID Helicopter/
├── MPU6050_IMU_Demo/          our lab code + PROMPT_LOG.md (unchanged, tracked in git)
├── PWM_Demo/                  course PWM demo (unchanged, tracked in git)
└── final_report/
    ├── SESSION_LOG_final_report.md   this file
    ├── output/                       ← the reports to hand in
    │   ├── claude_report_final.pdf     detailed version, full derivations (51 pages)
    │   ├── claude_report_final.docx    same, Word
    │   ├── claude_report_simple.pdf    easier language, final formulas only (49 pages)
    │   └── claude_report_simple.docx   same, Word
    ├── build/                        scripts that generate the reports
    │   ├── content.py                  text of the detailed report
    │   ├── content_simple.py           text of the easier report
    │   ├── appendix.py                 Appendix A (code) and B (prompt log) generators
    │   ├── build_report.py             HTML → PDF (headless Chrome)
    │   ├── make_docx.py                HTML → Word
    │   ├── make_formulas.py            formula images
    │   ├── make_diagrams.py            pinout and block-diagram SVGs
    │   ├── report.html, report_simple.html
    │   └── figures/                    all images used in the reports
    └── sources/                      material the report was built from
        ├── drafts/                     official_report_11_8_26.pdf, claude_report.pdf, SESSION_LOG_Lab3_Report.md
        ├── readings/                   the 7 course-page PDFs
        └── media/                      VGA screenshots, arm photos, demo videos
```

## Rebuilding

Run these from `final_report/build/`:

```
python3 make_formulas.py && python3 make_diagrams.py   # formula images and diagrams
python3 build_report.py                                # → output/claude_report_final.pdf
python3 build_report.py simple                         # → output/claude_report_simple.pdf
pip install python-docx beautifulsoup4                 # once, for the Word files
python3 make_docx.py                                   # → output/claude_report_simple.docx
python3 make_docx.py full                              # → output/claude_report_final.docx
```

Run `build_report.py` before `make_docx.py`, because the Word files are made from the HTML it writes. Edit `content.py` or `content_simple.py` to change the text.

## Still to check before submitting

- Scroll through both Word files in Word or Google Docs. Only page 1 could be previewed here; the most likely problem spots are the side-by-side screenshot/photo pairs and the wide prompt-log table.
- If AI wrote the demo-button sequence or the overcurrent-protection code, add log entries for them. They are marked ADDED in the code but aren't in `PROMPT_LOG.md`.
- Confirm the cover date (11.08.2026) and the AI-use wording in Section 8.
- The overshoot values and the d/r ≈ 0.4–0.5 fit are estimates read from screenshots.
