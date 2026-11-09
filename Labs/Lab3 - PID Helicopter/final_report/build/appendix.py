"""Appendix generators: verbatim code listing (Appendix A) and AI prompt log (Appendix B).

The code listing is read straight from ../../MPU6050_IMU_Demo so it always matches the code we ran.
The prompt log is built only from ../../MPU6050_IMU_Demo/PROMPT_LOG.md.
"""
import html
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "..", "MPU6050_IMU_Demo")

# ---------------------------------------------------------------------------
# Appendix A: code listing
# ---------------------------------------------------------------------------
BEGIN = re.compile(r"=====\s*(ADDED|CHANGED)\b")
END = re.compile(r"=====\s*END\b")
SINGLE = re.compile(r"//\s*(ADDED|CHANGED|FIXED|REMOVED)\b|\b(CHANGED|FIXED|REMOVED):")


def _shade_lines(lines):
    """Return a set of line indices inside ADDED/CHANGED blocks or carrying a one-line marker."""
    shaded, stack, spans = set(), [], []
    for i, ln in enumerate(lines):
        if END.search(ln):
            if stack:
                spans.append((stack.pop(), i))
        elif BEGIN.search(ln):
            stack.append(i)
    for a, b in spans:
        shaded.update(range(a, b + 1))
    for i in stack:  # unmatched header: shade just that line
        shaded.add(i)
    for i, ln in enumerate(lines):
        if SINGLE.search(ln):
            shaded.add(i)
    return shaded


def _hl(line):
    """Escape a C line and colour its // comment, if any (ignores // inside strings)."""
    in_str, idx = False, -1
    for k, ch in enumerate(line):
        if ch == '"' and (k == 0 or line[k - 1] != "\\"):
            in_str = not in_str
        if not in_str and line.startswith("//", k):
            idx = k
            break
    if idx < 0:
        stripped = line.lstrip()
        if stripped.startswith(("/*", "*", "*/")):
            return f'<span class="cm">{html.escape(line)}</span>'
        if stripped.startswith("#"):
            return f'<span class="pp">{html.escape(line)}</span>'
        return html.escape(line)
    return html.escape(line[:idx]) + f'<span class="cm">{html.escape(line[idx:])}</span>'


def code_listing(fname, label):
    path = os.path.join(SRC, fname)
    lines = open(path).read().expandtabs(4).rstrip("\n").split("\n")
    shaded = _shade_lines(lines) if fname.endswith(".c") else set()
    rows = []
    for i, ln in enumerate(lines):
        cls = ' class="ai"' if i in shaded else ""
        body = _hl(ln) if not fname.endswith(".txt") else html.escape(ln)
        rows.append(f'<tr{cls}><td class="ln">{i+1}</td><td class="src">{body or "&#8203;"}</td></tr>')
    return (f'<h3 class="codehead">{label}</h3>'
            f'<table class="code">{"".join(rows)}</table>')


# ---------------------------------------------------------------------------
# Appendix B: prompt log
# ---------------------------------------------------------------------------
# Counted by comparing each suggestion with the final imu_demo.c.
# "Accepted" = the suggested code is still present in the final program (possibly edited later by us).
COUNTS = {
    1: ((3, 0, 1), (3, 0, 1), "Kept. We later renamed the manual-duty command from <code>p</code> to <code>n</code>."),
    2: ((0, 0, 0), (0, 0, 0), "Comment markers only; kept (the ADDED / CHANGED markers in Appendix A)."),
    3: ((0, 0, 0), (0, 0, 0), "Diagnosis only."),
    4: ((0, 0, 0), (0, 0, 0), "Diagnosis only (program hung in I2C setup)."),
    5: ((9, 0, 0), (7, 0, 0), "<code>#define PI</code> and the magenta accel-angle trace were later removed."),
    6: ((0, 1, 1), (0, 1, 1), "Kept: local Q15 macros deleted, 180/&pi; constant fixed."),
    7: ((4, 0, 2), (0, 0, 0), "WHO_AM_I check and <code>imu_ok</code> guards later removed by us; replaced by entry 10."),
    8: ((0, 0, 1), (0, 0, 0), "Removed together with the entry 7 check."),
    9: ((0, 0, 0), (0, 0, 0), "Created PROMPT_LOG.md."),
    10: ((1, 0, 0), (1, 0, 0), "Kept: I2C bus recovery at start-up."),
    11: ((1, 0, 5), (1, 0, 5), "Offered as a suggestion; we applied the axis change by hand (finished in entry 12)."),
    12: ((0, 0, 4), (0, 0, 4), "Kept: a<sub>z</sub> axis, +&pi; removed, plot offset removed, seed re-enabled."),
    13: ((7, 0, 3), (7, 0, 3), "Kept. We later renamed the Kp command from <code>k</code> to <code>p</code>."),
    14: ((1, 0, 0), (0, 0, 0), "PID + feed-forward sketch not used."),
    15: ((3, 0, 2), (3, 0, 2), "Kept."),
    16: ((1, 0, 2), (1, 0, 2), "Kept, but we later raised <code>DUTY_MAX</code> back to 6000."),
    17: ((6, 0, 1), (6, 0, 1), "Kept. We later raised <code>i_max</code> to 10000 and made <code>i 0</code> clear the integrator."),
    18: ((0, 0, 0), (0, 0, 0), "Tuning advice only."),
}


def _inline(s):
    s = html.escape(s, quote=False)
    s = re.sub(r"`([^`]+)`", r"<code>\1</code>", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    return s


def _md_block(text):
    """Tiny markdown renderer for the log's answer text: paragraphs, '-' and '1.' lists."""
    out, buf, mode = [], [], None

    def flush():
        nonlocal buf, mode
        if not buf:
            return
        if mode == "ul":
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in buf) + "</ul>")
        elif mode == "ol":
            out.append("<ol>" + "".join(f"<li>{_inline(x)}</li>" for x in buf) + "</ol>")
        else:
            out.append(f"<p>{_inline(' '.join(buf))}</p>")
        buf, mode = [], None

    for ln in text.split("\n"):
        if not ln.strip():
            flush()
            continue
        m_ul = re.match(r"^\s*-\s+(.*)", ln)
        m_ol = re.match(r"^\s*\d+\.\s+(.*)", ln)
        if m_ul:
            if mode != "ul":
                flush(); mode = "ul"
            buf.append(m_ul.group(1))
        elif m_ol:
            if mode != "ol":
                flush(); mode = "ol"
            buf.append(m_ol.group(1))
        else:
            if mode in ("ul", "ol"):
                buf[-1] += " " + ln.strip()
            else:
                mode = "p"; buf.append(ln.strip())
    flush()
    return "".join(out)


def parse_log():
    t = open(os.path.join(SRC, "PROMPT_LOG.md")).read()
    parts = re.split(r"\n## (\d+)\. ", t)[1:]
    entries = []
    for i in range(0, len(parts), 2):
        n = int(parts[i])
        body = parts[i + 1].split("\n---")[0]
        title = body.split("\n")[0].strip()
        date = re.search(r"\*\*Date:\*\* (\S+)", body).group(1)
        pm = re.search(r"\*\*Prompt:\*\*\n(.*?)\n\n\*\*Answer", body, re.S).group(1)
        prompt = "\n".join(l[2:] if l.startswith("> ") else l.lstrip(">") for l in pm.split("\n"))
        ans = re.search(r"\*\*Answer:\*\*\n(.*?)\n\n\*\*Code", body, re.S).group(1)
        code_label = re.search(r"\*\*Code[^*]*\*\*[^\n]*", body).group(0)
        code = re.search(r"```c\n(.*?)```", body, re.S)
        entries.append(dict(n=n, title=title, date=date, prompt=prompt.strip(), answer=ans.strip(),
                            code_label=code_label, code=code.group(1).rstrip() if code else None))
    return entries


def _fmt(t):
    return " / ".join(str(x) for x in t)


def prompt_log():
    entries = parse_log()
    tot = {"pw": 0, "rw": 0, "cl": 0, "s": [0, 0, 0], "a": [0, 0, 0]}
    rows = []
    for e in entries:
        pw = len(e["prompt"].split())
        rw = len(e["answer"].split())
        cl = len(e["code"].split("\n")) if e["code"] else 0
        s, a, note = COUNTS[e["n"]]
        tot["pw"] += pw; tot["rw"] += rw; tot["cl"] += cl
        for k in range(3):
            tot["s"][k] += s[k]; tot["a"][k] += a[k]
        e.update(pw=pw, rw=rw, cl=cl)
        rows.append(f"<tr><td>{e['n']}</td><td style='white-space:nowrap'>{e['date'][5:].replace('-', '/')}</td><td>{_inline(e['title'])}</td>"
                    f"<td>{pw}</td><td>{rw}</td><td>{cl}</td><td>{_fmt(s)}</td><td>{_fmt(a)}</td>"
                    f"<td class='note'>{note}</td></tr>")
    rows.append(f"<tr class='tot'><td colspan='3'>Total (18 prompts)</td><td>{tot['pw']}</td><td>{tot['rw']}</td>"
                f"<td>{tot['cl']}</td><td>{_fmt(tot['s'])}</td><td>{_fmt(tot['a'])}</td><td></td></tr>")
    table = ("<table class='log'><thead><tr><th>#</th><th>Date</th><th>Prompt (topic)</th>"
             "<th>Prompt words</th><th>Response words</th><th>Code lines given</th>"
             "<th>Suggested<br>add / del / mod</th><th>Accepted<br>add / del / mod</th><th>Notes</th></tr></thead>"
             f"<tbody>{''.join(rows)}</tbody></table>")

    blocks = []
    for e in entries:
        code_html = ""
        if e["code"]:
            code_html = (f"<div class='lab'>{_inline(e['code_label'].replace('**', ''))}</div>"
                         f"<pre class='logcode'>{html.escape(e['code'])}</pre>")
        else:
            code_html = f"<div class='lab'>{_inline(e['code_label'].replace('**', ''))}</div>"
        blocks.append(
            f"<div class='entry'><h4>B.{e['n']} &nbsp;{_inline(e['title'])} "
            f"<span class='meta'>{e['date']} &middot; {e['pw']} prompt words &middot; {e['rw']} response words</span></h4>"
            f"<div class='lab'>Our prompt (verbatim)</div><blockquote>{_inline(e['prompt']).replace(chr(10), '<br>')}</blockquote>"
            f"<div class='lab'>Claude's response (Claude Opus 5.5, Claude Code)</div>{_md_block(e['answer'])}"
            f"{code_html}</div>")
    return table, "".join(blocks), tot
