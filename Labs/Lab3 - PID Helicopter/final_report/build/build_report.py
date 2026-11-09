"""Build the final Lab 3 report: report.html -> ../output/claude_report_final.pdf (headless Chrome).

Run from this folder:
    python3 make_formulas.py && python3 make_diagrams.py && python3 build_report.py
    python3 build_report.py simple      (plain-language copy -> ../output/claude_report_simple.pdf)
"""
import importlib
import os
import re
import subprocess
import sys

import appendix

HERE = os.path.dirname(os.path.abspath(__file__))
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
# "python3 build_report.py" -> full report; "python3 build_report.py simple" -> plain-language copy
SIMPLE = len(sys.argv) > 1 and sys.argv[1] == "simple"
BODY = importlib.import_module("content_simple" if SIMPLE else "content").BODY
PDF = os.path.join(HERE, "..", "output", "claude_report_simple.pdf" if SIMPLE else "claude_report_final.pdf")
HTML = os.path.join(HERE, "report_simple.html" if SIMPLE else "report.html")

CSS = r"""
@page { size: Letter; margin: 0.85in 0.8in 0.8in 0.8in;
  @top-left { content: "Li_Huang_Karim_Thursday"; font: 9pt Helvetica, Arial, sans-serif; color: #555; }
  @top-right { content: "ECE 5730 Lab 3: 1D Helicopter"; font: 9pt Helvetica, Arial, sans-serif; color: #555; }
  @bottom-center { content: counter(page); font: 9pt Helvetica, Arial, sans-serif; color: #555; } }
@page :first { @top-left { content: none; } @top-right { content: none; } @bottom-center { content: none; } }
html { font-family: "Charter", "Georgia", serif; font-size: 10.6pt; line-height: 1.42; color: #111; }
body { margin: 0; }
h1, h2, h3, h4 { font-family: Helvetica, Arial, sans-serif; color: #0b2545; line-height: 1.2; }
h1.sec { font-size: 17pt; margin: 0 0 8pt; padding-bottom: 4pt; border-bottom: 2px solid #0b2545; break-before: page; }
h2 { font-size: 13pt; margin: 14pt 0 5pt; break-after: avoid; }
h3 { font-size: 11pt; margin: 11pt 0 4pt; break-after: avoid; }
h4 { font-size: 10pt; margin: 9pt 0 3pt; break-after: avoid; }
p { margin: 0 0 6.5pt; text-align: justify; hyphens: auto; }
ul, ol { margin: 0 0 6.5pt 0; padding-left: 18pt; }
li { margin-bottom: 2pt; }
code { font-family: Menlo, Consolas, monospace; font-size: 8.8pt; background: #f2f4f7; padding: 0 2px; border-radius: 2px; }
.title { height: 9in; display: flex; flex-direction: column; justify-content: center; text-align: center; }
.title .course { font: 600 13pt Helvetica, Arial, sans-serif; color: #555; letter-spacing: 1px; }
.title h1 { font-size: 28pt; margin: 10pt 0 4pt; border: none; }
.title .sub { font: 15pt Helvetica, Arial, sans-serif; color: #0b2545; margin-bottom: 26pt; }
.title .names { font: 13pt Helvetica, Arial, sans-serif; }
.title .date { font: 11pt Helvetica, Arial, sans-serif; color: #555; margin-top: 6pt; }
.title img { width: 78%; margin: 26pt auto 0; border-radius: 4px; }
.title .tag { font: 10pt Helvetica, Arial, sans-serif; color: #777; margin-top: 30pt; }
figure { margin: 8pt 0 10pt; text-align: center; break-inside: avoid; }
figure img { max-width: 100%; }
figcaption { font: 9pt/1.35 Helvetica, Arial, sans-serif; color: #333; text-align: left; margin-top: 4pt; }
.eq { text-align: center; margin: 6pt 0 8pt; break-inside: avoid; }
.eq img { height: auto; }
.pair { display: grid; grid-template-columns: 1.62fr 1fr; gap: 8pt; align-items: center; }
.pair img { width: 100%; border-radius: 3px; border: 1px solid #ddd; }
.pair .ph { max-height: 3.0in; object-fit: contain; }
.two { display: grid; grid-template-columns: 1fr 1fr; gap: 10pt; align-items: center; }
table.t { border-collapse: collapse; width: 100%; margin: 4pt 0 4pt; font: 9pt/1.3 Helvetica, Arial, sans-serif; break-inside: avoid; }
table.t th { background: #0b2545; color: #fff; text-align: left; padding: 3pt 5pt; font-weight: 600; }
table.t td { border-bottom: 1px solid #d7dce3; padding: 3pt 5pt; vertical-align: top; }
table.t tr:nth-child(even) td { background: #f6f8fb; }
.tcap { font: 9pt Helvetica, Arial, sans-serif; color: #333; margin: 0 0 10pt; }
.callout { border-left: 3px solid #0b2545; background: #f2f5fa; padding: 5pt 9pt; margin: 6pt 0 9pt; font-size: 10pt; break-inside: avoid; }
.callout p:last-child { margin-bottom: 0; }
.q { border: 1px solid #c9d3e0; border-radius: 4px; padding: 7pt 10pt 4pt; margin: 0 0 10pt; break-inside: avoid-page; }
.q h3 { margin-top: 0; }
pre.snip { font: 7.3pt/1.4 Menlo, Consolas, monospace; background: #f6f8fb; border: 1px solid #dde3ea; padding: 6pt 8pt; white-space: pre; overflow: hidden; break-inside: avoid; }
/* code listing */
h3.codehead { break-before: auto; margin-top: 14pt; }
table.code { border-collapse: collapse; width: 100%; font: 7.3pt/1.32 Menlo, Consolas, monospace; }
table.code td { padding: 0 4pt; vertical-align: top; }
table.code td.ln { color: #999; text-align: right; width: 22pt; user-select: none; border-right: 1px solid #ddd; }
table.code td.src { white-space: pre-wrap; word-break: break-word; }
table.code tr.ai td.src { background: #fff6d6; }
table.code tr.ai td.ln { background: #ffe9a3; color: #6b5200; }
.cm { color: #2f7d32; } .pp { color: #8a3ffc; }
.legend { display: inline-block; width: 12pt; height: 9pt; background: #fff6d6; border: 1px solid #e0c96b; vertical-align: middle; }
/* prompt log */
table.log { border-collapse: collapse; width: 100%; font: 7.8pt/1.25 Helvetica, Arial, sans-serif; }
table.log th { background: #0b2545; color: #fff; padding: 3pt 3pt; text-align: left; font-weight: 600; }
table.log td { border-bottom: 1px solid #d7dce3; padding: 2.5pt 3pt; vertical-align: top; }
table.log td:nth-child(n+4):nth-child(-n+8) { text-align: center; white-space: nowrap; }
table.log tr.tot td { font-weight: 700; background: #e8edf5; }
table.log td.note { font-size: 7.3pt; color: #333; }
table.log code, table.t code { font-size: 0.92em; padding: 0 1px; }
.entry { border-top: 1px solid #c9d3e0; padding-top: 4pt; margin-top: 8pt; }
.entry h4 { margin: 2pt 0 4pt; font-size: 10pt; }
.entry .meta { font-weight: 400; color: #666; font-size: 8.5pt; margin-left: 6pt; }
.entry .lab { font: 600 8.3pt Helvetica, Arial, sans-serif; color: #0b2545; margin: 5pt 0 2pt; text-transform: uppercase; letter-spacing: .4px; }
.entry blockquote { margin: 0 0 4pt; padding: 3pt 8pt; border-left: 3px solid #9aa9bd; background: #f6f8fb; font-style: italic; font-size: 9.6pt; }
.entry p, .entry li { font-size: 9.6pt; }
pre.logcode { font: 7.3pt/1.3 Menlo, Consolas, monospace; background: #f6f8fb; border: 1px solid #dde3ea; padding: 5pt 7pt; white-space: pre-wrap; margin: 2pt 0 4pt; }
.toc { font: 10.5pt/1.7 Helvetica, Arial, sans-serif; columns: 2; column-gap: 24pt; }
.toc div.sub { padding-left: 14pt; color: #444; font-size: 9.6pt; line-height: 1.5; }
"""


def number(html_text):
    """Assign Figure / Table numbers in order of definition and resolve [[f:key]] / [[t:key]] refs."""
    figs = {k: i + 1 for i, k in enumerate(dict.fromkeys(re.findall(r'data-fig="([\w-]+)"', html_text)))}
    tabs = {k: i + 1 for i, k in enumerate(dict.fromkeys(re.findall(r'data-tab="([\w-]+)"', html_text)))}
    for k, n in figs.items():
        html_text = html_text.replace(f"[[fn:{k}]]", f"Figure {n}.").replace(f"[[f:{k}]]", f"Figure {n}")
    for k, n in tabs.items():
        html_text = html_text.replace(f"[[tn:{k}]]", f"Table {n}.").replace(f"[[t:{k}]]", f"Table {n}")
    left = re.findall(r"\[\[[a-z]+:[\w-]+\]\]", html_text)
    if left:
        raise SystemExit(f"unresolved references: {sorted(set(left))}")
    return html_text


def eq(name):
    """Equation image sized so every formula prints at the same font size (rendered at 220 dpi, 15 pt)."""
    from PIL import Image
    w = Image.open(os.path.join(HERE, "figures", f"eq_{name}.png")).width
    return f'<div class="eq"><img src="figures/eq_{name}.png" style="width:{w / 220 * 0.78:.2f}in"></div>'


def main():
    log_table, log_entries, tot = appendix.prompt_log()
    code = "".join([
        appendix.code_listing("imu_demo.c", "A.1 &nbsp;imu_demo.c (main program: ISR, controller, display, serial)"),
        appendix.code_listing("mpu6050.c", "A.2 &nbsp;mpu6050.c (IMU driver, course code)"),
        appendix.code_listing("mpu6050.h", "A.3 &nbsp;mpu6050.h (pins, fix15 macros and constants)"),
        appendix.code_listing("CMakeLists.txt", "A.4 &nbsp;CMakeLists.txt (build)"),
    ])
    body = BODY
    body = re.sub(r"\{\{eq:(\w+)\}\}", lambda m: eq(m.group(1)), body)
    body = (body.replace("{{CODE}}", code).replace("{{LOG_TABLE}}", log_table)
            .replace("{{LOG_ENTRIES}}", log_entries)
            .replace("{{TOT_PW}}", str(tot["pw"])).replace("{{TOT_RW}}", str(tot["rw"]))
            .replace("{{TOT_CL}}", str(tot["cl"]))
            .replace("{{TOT_S}}", " / ".join(map(str, tot["s"])))
            .replace("{{TOT_A}}", " / ".join(map(str, tot["a"]))))
    body = number(body)
    doc = (f'<!DOCTYPE html><html lang="en"><head><meta charset="utf-8">'
           f'<title>ECE 5730 Lab 3 Report: PID Control of a 1D Helicopter</title><style>{CSS}</style></head>'
           f'<body>{body}</body></html>')
    out = HTML
    open(out, "w").write(doc)
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--no-pdf-header-footer",
                    "--allow-file-access-from-files", f"--print-to-pdf={os.path.abspath(PDF)}",
                    "file://" + out], check=True, stderr=subprocess.DEVNULL)
    print("wrote", out, "and", os.path.abspath(PDF))


if __name__ == "__main__":
    main()
