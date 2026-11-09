"""Convert a built report HTML (report_simple.html by default) to a Word document.

Run after build_report.py:
    python3 build_report.py simple
    <python with python-docx + beautifulsoup4> make_docx.py            -> ../output/claude_report_simple.docx
    <python with python-docx + beautifulsoup4> make_docx.py full       -> ../output/claude_report_final.docx

Needs: python-docx, beautifulsoup4, pillow, and Google Chrome (to rasterise the two SVG diagrams).
"""
import copy
import os
import re
import subprocess
import sys

from bs4 import BeautifulSoup, Comment, NavigableString, Tag
from docx import Document
from docx.enum.section import WD_SECTION
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_BREAK, WD_TAB_ALIGNMENT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor
from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
FULL = len(sys.argv) > 1 and sys.argv[1] == "full"
SRC_HTML = os.path.join(HERE, "report.html" if FULL else "report_simple.html")
OUT = os.path.join(HERE, "..", "output", "claude_report_final.docx" if FULL else "claude_report_simple.docx")
CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
RASTER = os.path.join(HERE, "figures", "_docx")

TEXT_W = 6.9  # inches between margins (8.5 - 2 x 0.8)
NAVY = RGBColor(0x0B, 0x25, 0x45)
GREY = RGBColor(0x55, 0x55, 0x55)
GREEN = RGBColor(0x2F, 0x7D, 0x32)
PURPLE = RGBColor(0x8A, 0x3F, 0xFC)
BODY_FONT, HEAD_FONT, MONO = "Georgia", "Arial", "Consolas"


# ---------------------------------------------------------------- low-level XML helpers
ORDER = {
    "pPr": "pStyle keepNext keepLines pageBreakBefore framePr widowControl numPr suppressLineNumbers pBdr shd tabs "
           "suppressAutoHyphens kinsoku wordWrap overflowPunct topLinePunct autoSpaceDE autoSpaceDN bidi adjustRightInd "
           "snapToGrid spacing ind contextualSpacing mirrorIndents suppressOverlap jc textDirection textAlignment "
           "textboxTightWrap outlineLvl divId cnfStyle rPr sectPr pPrChange",
    "rPr": "rStyle rFonts b bCs i iCs caps smallCaps strike dstrike outline shadow emboss imprint noProof snapToGrid "
           "vanish webHidden color spacing w kern position sz szCs highlight u effect bdr shd fitText vertAlign rtl cs "
           "em lang eastAsianLayout specVanish oMath",
    "tcPr": "cnfStyle tcW gridSpan hMerge vMerge tcBorders shd noWrap tcMar textDirection tcFitText vAlign hideMark",
    "tblPr": "tblStyle tblpPr tblOverlap bidiVisual tblStyleRowBandSize tblStyleColBandSize tblW jc tblCellSpacing "
             "tblInd tblBorders shd tblLayout tblCellMar tblLook tblCaption tblDescription",
}


def put(parent, el):
    """Insert el into parent at the position the OOXML schema requires (replacing an existing same-tag child)."""
    kind = parent.tag.split("}")[1]
    order = ORDER[kind].split()
    tag = el.tag.split("}")[1]
    old = parent.find(qn(f"w:{tag}"))
    if old is not None:
        parent.remove(old)
    later = set(order[order.index(tag) + 1:])
    for i, ch in enumerate(parent):
        if ch.tag.split("}")[1] in later:
            parent.insert(i, el)
            return el
    parent.append(el)
    return el


def shade(el_pr, fill):
    shd = OxmlElement("w:shd")
    shd.set(qn("w:val"), "clear"); shd.set(qn("w:color"), "auto"); shd.set(qn("w:fill"), fill)
    put(el_pr, shd)


def para_shade(p, fill):
    shade(p._p.get_or_add_pPr(), fill)


def para_border(p, side, color, sz=12, space=4):
    pPr = p._p.get_or_add_pPr()
    bdr = pPr.find(qn("w:pBdr"))
    if bdr is None:
        bdr = put(pPr, OxmlElement("w:pBdr"))
    b = OxmlElement(f"w:{side}")
    b.set(qn("w:val"), "single"); b.set(qn("w:sz"), str(sz)); b.set(qn("w:space"), str(space)); b.set(qn("w:color"), color)
    bdr.append(b)


def cell_shade(cell, fill):
    shade(cell._tc.get_or_add_tcPr(), fill)


def table_borders(table, color="D7DCE3", inside_v=False, outer=False, sz=4):
    tblPr = table._tbl.tblPr
    b = OxmlElement("w:tblBorders")
    for side in ("top", "left", "bottom", "right", "insideH", "insideV"):
        e = OxmlElement(f"w:{side}")
        on = (side == "insideH") or (side == "bottom") or (outer and side in ("top", "left", "right")) or (inside_v and side == "insideV")
        e.set(qn("w:val"), "single" if on else "nil")
        if on:
            e.set(qn("w:sz"), str(sz)); e.set(qn("w:space"), "0"); e.set(qn("w:color"), color)
        b.append(e)
    put(tblPr, b)


def cell_margins(table, top=40, bottom=40, left=80, right=80):
    tblPr = table._tbl.tblPr
    m = OxmlElement("w:tblCellMar")
    for side, v in (("top", top), ("left", left), ("bottom", bottom), ("right", right)):
        e = OxmlElement(f"w:{side}"); e.set(qn("w:w"), str(v)); e.set(qn("w:type"), "dxa"); m.append(e)
    put(tblPr, m)


def no_split_row(row):
    trPr = row._tr.get_or_add_trPr()
    e = OxmlElement("w:cantSplit"); trPr.append(e)


def header_row(row):
    trPr = row._tr.get_or_add_trPr()
    e = OxmlElement("w:tblHeader"); trPr.append(e)


def set_widths(table, widths_in):
    table.autofit = False
    tblPr = table._tbl.tblPr
    lay = OxmlElement("w:tblLayout"); lay.set(qn("w:type"), "fixed"); put(tblPr, lay)
    grid = table._tbl.tblGrid
    for gc, w in zip(grid.findall(qn("w:gridCol")), widths_in):
        gc.set(qn("w:w"), str(int(w * 1440)))
    for row in table.rows:
        for c, w in zip(row.cells, widths_in):
            c.width = Inches(w)


def add_field(run, instr):
    for kind, text in (("begin", None), (None, instr), ("separate", None), (None, "1"), ("end", None)):
        if kind:
            f = OxmlElement("w:fldChar"); f.set(qn("w:fldCharType"), kind); run._r.append(f)
        elif text == instr:
            t = OxmlElement("w:instrText"); t.set(qn("xml:space"), "preserve"); t.text = instr; run._r.append(t)
        else:
            t = OxmlElement("w:t"); t.text = text; run._r.append(t)


def spacing(p, before=0, after=0, line=None):
    pf = p.paragraph_format
    pf.space_before = Pt(before); pf.space_after = Pt(after)
    if line:
        pf.line_spacing = line


# ---------------------------------------------------------------- images
def rasterise_svg(path):
    os.makedirs(RASTER, exist_ok=True)
    out = os.path.join(RASTER, os.path.basename(path)[:-4] + ".png")
    vb = re.search(r'viewBox="0 0 (\d+) (\d+)"', open(path).read())
    w, h = int(vb.group(1)), int(vb.group(2))
    scale = 2
    wrapper = os.path.join(RASTER, "_wrap.html")
    open(wrapper, "w").write(f'<html><body style="margin:0;background:#fff">'
                             f'<img src="file://{path}" style="width:{w * scale}px;height:{h * scale}px;display:block"></body></html>')
    subprocess.run([CHROME, "--headless", "--disable-gpu", "--hide-scrollbars", "--allow-file-access-from-files",
                    f"--window-size={w * scale},{h * scale}", f"--screenshot={out}", "file://" + wrapper],
                   check=True, stderr=subprocess.DEVNULL, stdout=subprocess.DEVNULL)
    os.remove(wrapper)
    return out


def img_path(src):
    p = os.path.join(HERE, src)
    return rasterise_svg(p) if p.endswith(".svg") else p


def style_width(tag, avail):
    st = tag.get("style", "")
    m = re.search(r"width:\s*([\d.]+)in", st)
    if m:
        return float(m.group(1))
    m = re.search(r"width:\s*([\d.]+)%", st)
    return avail * float(m.group(1)) / 100 if m else avail


def add_picture(par, src, width_in, max_h=None):
    path = img_path(src)
    w, h = Image.open(path).size
    if max_h and width_in * h / w > max_h:
        width_in = max_h * w / h
    par.add_run().add_picture(path, width=Inches(width_in))


# ---------------------------------------------------------------- inline content
def inline(par, node, fmt=None, size=None):
    fmt = fmt or {}
    if isinstance(node, Comment):
        return
    if isinstance(node, NavigableString):
        text = re.sub(r"\s+", " ", str(node))
        if not text:
            return
        r = par.add_run(text)
        apply_fmt(r, fmt, size)
        return
    if not isinstance(node, Tag):
        return
    f = dict(fmt)
    name, cls = node.name, node.get("class", [])
    if name in ("b", "strong"):
        f["bold"] = True
    elif name in ("i", "em"):
        f["italic"] = True
    elif name == "sub":
        f["sub"] = True
    elif name == "sup":
        f["sup"] = True
    elif name == "code":
        f["code"] = True
    elif name == "br":
        par.add_run().add_break(); return
    elif name == "img":
        add_picture(par, node["src"], 1.0); return
    elif name == "span" and "legend" in cls:
        r = par.add_run("  "); shade(r._r.get_or_add_rPr(), "FFF6D6"); return
    elif name == "span" and "meta" in cls:
        f["color"] = GREY; f["bold"] = False; f["size"] = 8.5
    elif name == "span" and "cm" in cls:
        f["color"] = GREEN
    elif name == "span" and "pp" in cls:
        f["color"] = PURPLE
    for ch in node.children:
        inline(par, ch, f, size)


def apply_fmt(r, f, size):
    if f.get("bold"): r.bold = True
    if f.get("bold") is False: r.bold = False
    if f.get("italic"): r.italic = True
    if f.get("sub"): r.font.subscript = True
    if f.get("sup"): r.font.superscript = True
    if f.get("color") is not None: r.font.color.rgb = f["color"]
    if f.get("code"):
        r.font.name = MONO
        r.font.size = Pt((size or 10.5) * 0.85)
        shade(r._r.get_or_add_rPr(), "F2F4F7")
    elif f.get("size"):
        r.font.size = Pt(f["size"])
    elif size:
        r.font.size = Pt(size)


def trim(par):
    runs = [r for r in par.runs if r.text]
    if runs:
        runs[0].text = runs[0].text.lstrip()
        runs[-1].text = runs[-1].text.rstrip()


def text_par(container, node, style=None, size=None, align=None, fmt=None):
    p = container.add_paragraph(style=style)
    for ch in node.children:
        inline(p, ch, fmt, size)
    trim(p)
    if align is not None:
        p.alignment = align
    return p


def caption(container, node):
    p = text_par(container, node, style="Caption", size=8.5)
    return p


# ---------------------------------------------------------------- block content
class R:
    def __init__(self, doc):
        self.doc = doc

    def blocks(self, container, node, avail=TEXT_W):
        for ch in node.children:
            if isinstance(ch, Comment):
                continue
            if isinstance(ch, Tag):
                self.block(container, ch, avail)
            elif isinstance(ch, NavigableString) and ch.strip():
                p = container.add_paragraph(); inline(p, ch); trim(p)

    def block(self, c, el, avail=TEXT_W):
        name, cls, st = el.name, el.get("class", []), el.get("style", "")
        if name == "section" and "title" in cls:
            return self.title(el)
        if name == "h1":
            if "sec" in cls and "break-before: auto" not in st and "break-before:auto" not in st:
                # explicit page break (honoured by every viewer, unlike pageBreakBefore); its paragraph mark is 1 pt
                br = c.add_paragraph(); spacing(br, 0, 0, 1.0)
                r = br.add_run(); r.add_break(WD_BREAK.PAGE)
                mark = br._p.get_or_add_pPr()
                rpr = OxmlElement("w:rPr"); sz = OxmlElement("w:sz"); sz.set(qn("w:val"), "2"); rpr.append(sz)
                put(mark, rpr); r.font.size = Pt(1)
            text_par(c, el, style="Heading 1")
            return
        if name in ("h2", "h3", "h4"):
            text_par(c, el, style={"h2": "Heading 2", "h3": "Heading 3", "h4": "Heading 4"}[name]); return
        if name == "p":
            size = 9.4 if "font-size" in st else None
            text_par(c, el, size=size); return
        if name in ("ul", "ol"):
            return self.lst(c, el, ordered=(name == "ol"))
        if name == "div":
            if "eq" in cls:
                img = el.find("img")
                p = c.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; spacing(p, 3, 6)
                add_picture(p, img["src"], min(style_width(img, avail), avail)); return
            if "toc" in cls:
                for d in el.find_all("div", recursive=False):
                    sub = "sub" in d.get("class", [])
                    p = text_par(c, d, size=9.5 if sub else 11)
                    spacing(p, 0, 3 if sub else 1)
                    if sub:
                        p.paragraph_format.left_indent = Inches(0.3); [setattr(r.font.color, "rgb", GREY) for r in p.runs]
                    else:
                        for r in p.runs: r.font.name = HEAD_FONT
                return
            if "tcap" in cls:
                caption(c, el); return
            if "callout" in cls:
                for p_el in el.find_all("p"):
                    p = text_par(c, p_el)
                    para_shade(p, "F2F5FA"); para_border(p, "left", "0B2545", sz=18, space=8)
                    p.paragraph_format.left_indent = Inches(0.1)
                return
            if "q" in cls:
                t = c.add_table(rows=1, cols=1)
                table_borders(t, color="C9D3E0", outer=True, sz=8); cell_margins(t, 100, 60, 140, 140)
                set_widths(t, [avail])
                cell = t.cell(0, 0)
                cell._tc.remove(cell.paragraphs[0]._p)
                self.blocks(cell, el, avail - 0.2)
                c.add_paragraph().paragraph_format.space_after = Pt(2)
                return
            if "two" in cls:
                figs = el.find_all("figure", recursive=False)
                t = c.add_table(rows=1, cols=len(figs)); table_borders(t, color="FFFFFF"); cell_margins(t, 0, 0, 60, 60)
                w = avail / len(figs); set_widths(t, [w] * len(figs))
                for cell, fg in zip(t.rows[0].cells, figs):
                    cell._tc.remove(cell.paragraphs[0]._p)
                    self.figure(cell, fg, w - 0.15)
                return
            if "entry" in cls:
                p = c.add_paragraph(); para_border(p, "top", "C9D3E0", sz=6, space=1); spacing(p, 6, 0)
                self.blocks(c, el, avail); return
            if "lab" in cls:
                p = text_par(c, el, size=8)
                spacing(p, 5, 1)
                for r in p.runs:
                    r.font.name = HEAD_FONT; r.bold = True; r.font.color.rgb = NAVY; r.font.all_caps = True
                return
            self.blocks(c, el, avail); return
        if name == "figure":
            return self.figure(c, el, avail)
        if name == "table":
            if "code" in cls:
                return self.code_listing(c, el)
            return self.table(c, el, avail, log=("log" in cls))
        if name == "pre":
            return self.pre(c, el, size=7.0 if "snip" in cls else 7.5)
        if name == "blockquote":
            p = text_par(c, el, size=9.5, fmt={"italic": True})
            para_shade(p, "F6F8FB"); para_border(p, "left", "9AA9BD", sz=18, space=6)
            p.paragraph_format.left_indent = Inches(0.1); spacing(p, 0, 4)
            return
        self.blocks(c, el, avail)

    def lst(self, c, el, ordered):
        n = 0
        for li in el.find_all("li", recursive=False):
            if "list-style:none" in li.get("style", ""):
                p = text_par(c, li, style="List Paragraph" if False else None)
                p.paragraph_format.left_indent = Inches(0.25)
                continue
            n += 1
            if ordered:
                p = c.add_paragraph()
                p.paragraph_format.left_indent = Inches(0.3); p.paragraph_format.first_line_indent = Inches(-0.22)
                p.add_run(f"{n}.\t")
                p.paragraph_format.tab_stops.add_tab_stop(Inches(0.3))
                for ch in li.children:
                    inline(p, ch)
                runs = [r for r in p.runs if r.text][1:]
                if runs: runs[0].text = runs[0].text.lstrip(); runs[-1].text = runs[-1].text.rstrip()
            else:
                p = text_par(c, li, style="List Bullet")
            spacing(p, 0, 2)

    def figure(self, c, el, avail):
        pair = el.find("div", class_="pair")
        if pair:
            imgs = pair.find_all("img")
            t = c.add_table(rows=1, cols=2); table_borders(t, color="FFFFFF"); cell_margins(t, 0, 0, 40, 40)
            ws = [avail * 1.62 / 2.62, avail * 1 / 2.62]; set_widths(t, ws)
            for cell, img, w in zip(t.rows[0].cells, imgs, ws):
                p = cell.paragraphs[0]; p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                add_picture(p, img["src"], w - 0.1, max_h=3.0 if "ph" in img.get("class", []) else None)
        else:
            img = el.find("img")
            p = c.add_paragraph(); p.alignment = WD_ALIGN_PARAGRAPH.CENTER; spacing(p, 4, 2)
            p.paragraph_format.keep_with_next = True
            add_picture(p, img["src"], style_width(img, avail))
        cap = el.find("figcaption")
        if cap:
            caption(c, cap)

    def table(self, c, el, avail, log=False):
        rows = el.find_all("tr")
        ncol = max(len(r.find_all(["td", "th"])) for r in rows)
        t = c.add_table(rows=0, cols=ncol)
        t.alignment = WD_TABLE_ALIGNMENT.CENTER
        table_borders(t); cell_margins(t, 30, 30, 70, 70)
        size = 7.3 if log else 8.6
        # column widths: explicit % on the first header row, rest shared equally
        if log:
            widths = [0.25, 0.42, 1.45, 0.48, 0.55, 0.48, 0.72, 0.72, 1.83]
        else:
            ths = rows[0].find_all(["th", "td"])
            fixed = {}
            for i, th in enumerate(ths):
                m = re.search(r"width:\s*([\d.]+)%", th.get("style", ""))
                if m: fixed[i] = avail * float(m.group(1)) / 100
            rest = (avail - sum(fixed.values())) / max(1, ncol - len(fixed))
            widths = [fixed.get(i, rest) for i in range(ncol)]
        for ri, tr in enumerate(rows):
            cells_el = tr.find_all(["td", "th"])
            row = t.add_row(); no_split_row(row)
            is_head = all(x.name == "th" for x in cells_el)
            if is_head:
                header_row(row)
            ci = 0
            for x in cells_el:
                span = int(x.get("colspan", 1))
                cell = row.cells[ci]
                if span > 1:
                    cell = cell.merge(row.cells[ci + span - 1])
                p = cell.paragraphs[0]; spacing(p, 0, 0, 1.0)
                for ch in x.children:
                    inline(p, ch, None, size)
                trim(p)
                for r in p.runs:
                    if r.font.name != MONO: r.font.name = HEAD_FONT
                    if not r.font.size: r.font.size = Pt(size)
                if "note" in x.get("class", []):
                    for r in p.runs: r.font.size = Pt(size - 0.5)
                if is_head:
                    cell_shade(cell, "0B2545")
                    for r in p.runs: r.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF); r.bold = True
                elif "tot" in tr.get("class", []):
                    cell_shade(cell, "E8EDF5")
                    for r in p.runs: r.bold = True
                elif ri % 2 == 0:
                    cell_shade(cell, "F6F8FB")
                if log and 3 <= ci <= 7 and not is_head:
                    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                ci += span
        set_widths(t, widths)
        c.add_paragraph().paragraph_format.space_after = Pt(0)

    def pre(self, c, el, size):
        lines = el.get_text().rstrip("\n").split("\n")
        for i, ln in enumerate(lines):
            p = c.add_paragraph(); spacing(p, 0, 0, 1.0)
            r = p.add_run(ln if ln else "​"); r.font.name = MONO; r.font.size = Pt(size)
            para_shade(p, "F6F8FB")
            p.paragraph_format.keep_with_next = i < len(lines) - 1 and len(lines) < 30
        spacing(p, 0, 6, 1.0)

    def code_listing(self, c, el):
        for tr in el.find_all("tr"):
            ln = tr.find("td", class_="ln").get_text()
            src = tr.find("td", class_="src")
            p = c.add_paragraph(); spacing(p, 0, 0, 1.0)
            pf = p.paragraph_format
            pf.left_indent = Inches(0.42); pf.first_line_indent = Inches(-0.42)
            pf.tab_stops.add_tab_stop(Inches(0.3), WD_TAB_ALIGNMENT.RIGHT)
            pf.tab_stops.add_tab_stop(Inches(0.42))
            r = p.add_run(f"\t{ln}\t"); r.font.name = MONO; r.font.size = Pt(6.8)
            r.font.color.rgb = RGBColor(0x6B, 0x52, 0x00) if "ai" in tr.get("class", []) else RGBColor(0x99, 0x99, 0x99)
            self._code_runs(p, src, {})
            if "ai" in tr.get("class", []):
                para_shade(p, "FFF6D6")

    def _code_runs(self, p, node, fmt):
        for ch in node.children:
            if isinstance(ch, NavigableString):
                txt = str(ch).replace("​", "")
                if txt:
                    r = p.add_run(txt); r.font.name = MONO; r.font.size = Pt(6.8)
                    if fmt.get("color") is not None: r.font.color.rgb = fmt["color"]
            elif isinstance(ch, Tag):
                f = dict(fmt)
                if "cm" in ch.get("class", []): f["color"] = GREEN
                if "pp" in ch.get("class", []): f["color"] = PURPLE
                self._code_runs(p, ch, f)

    def title(self, el):
        d = self.doc
        p = d.add_paragraph(); spacing(p, 90, 0)
        for div_cls, size, color, bold, after in (("course", 11, GREY, True, 14),):
            pass
        course = el.find("div", class_="course"); h1 = el.find("h1"); sub = el.find("div", class_="sub")
        names = el.find("div", class_="names"); date = el.find("div", class_="date")
        img = el.find("img"); tag = el.find("div", class_="tag")
        for node, size, color, bold, after in ((course, 11, GREY, True, 8), (h1, 28, NAVY, True, 4), (sub, 15, NAVY, False, 22),
                                               (names, 13, None, False, 4), (date, 11, GREY, False, 18)):
            q = d.add_paragraph(); q.alignment = WD_ALIGN_PARAGRAPH.CENTER; spacing(q, 0, after)
            inline(q, node); trim(q)
            for r in q.runs:
                r.font.name = HEAD_FONT; r.font.size = Pt(size); r.bold = bold
                if color is not None: r.font.color.rgb = color
        q = d.add_paragraph(); q.alignment = WD_ALIGN_PARAGRAPH.CENTER
        add_picture(q, img["src"], 2.6)
        q = d.add_paragraph(); q.alignment = WD_ALIGN_PARAGRAPH.CENTER; spacing(q, 14, 0)
        inline(q, tag); trim(q)
        for r in q.runs: r.font.name = HEAD_FONT; r.font.size = Pt(10); r.font.color.rgb = RGBColor(0x77, 0x77, 0x77)


# ---------------------------------------------------------------- document setup
def setup(doc):
    s = doc.sections[0]
    s.page_width, s.page_height = Inches(8.5), Inches(11)
    s.left_margin = s.right_margin = Inches(0.8)
    s.top_margin, s.bottom_margin = Inches(0.85), Inches(0.8)
    s.header_distance = s.footer_distance = Inches(0.4)
    s.different_first_page_header_footer = True

    st = doc.styles
    normal = st["Normal"]
    normal.font.name = BODY_FONT; normal.font.size = Pt(10.5)
    normal.element.rPr.rFonts.set(qn("w:eastAsia"), BODY_FONT)
    normal.paragraph_format.space_after = Pt(6); normal.paragraph_format.line_spacing = 1.2
    for name, size, before, after in (("Heading 1", 17, 6, 8), ("Heading 2", 13, 12, 4),
                                      ("Heading 3", 11, 9, 3), ("Heading 4", 10, 6, 3)):
        h = st[name]
        h.font.name = HEAD_FONT; h.font.size = Pt(size); h.font.bold = True; h.font.italic = False
        h.font.color.rgb = NAVY
        rf = h.element.rPr.rFonts
        for a in ("w:ascii", "w:hAnsi", "w:cs", "w:eastAsia"):
            rf.set(qn(a), HEAD_FONT)
        for a in ("w:asciiTheme", "w:hAnsiTheme", "w:cstheme", "w:eastAsiaTheme"):
            if rf.get(qn(a)) is not None: del rf.attrib[qn(a)]
        h.paragraph_format.space_before = Pt(before); h.paragraph_format.space_after = Pt(after)
        h.paragraph_format.keep_with_next = True
    h1 = st["Heading 1"]
    pPr = h1.element.get_or_add_pPr()
    bdr = OxmlElement("w:pBdr"); b = OxmlElement("w:bottom")
    b.set(qn("w:val"), "single"); b.set(qn("w:sz"), "12"); b.set(qn("w:space"), "3"); b.set(qn("w:color"), "0B2545")
    bdr.append(b); put(pPr, bdr)
    cap = st["Caption"]
    cap.font.name = HEAD_FONT; cap.font.size = Pt(8.5); cap.font.bold = False; cap.font.italic = False
    cap.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    cap.paragraph_format.space_after = Pt(9); cap.paragraph_format.space_before = Pt(2)
    lb = st["List Bullet"]; lb.paragraph_format.space_after = Pt(2)

    # header / footer (not on the title page)
    hp = s.header.paragraphs[0]
    hp.paragraph_format.tab_stops.add_tab_stop(Inches(TEXT_W), WD_TAB_ALIGNMENT.RIGHT)
    r = hp.add_run("Li_Huang_Karim_Thursday\tECE 5730 Lab 3: 1D Helicopter")
    r.font.name = HEAD_FONT; r.font.size = Pt(9); r.font.color.rgb = GREY
    fp = s.footer.paragraphs[0]; fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = fp.add_run(); r.font.name = HEAD_FONT; r.font.size = Pt(9); r.font.color.rgb = GREY
    add_field(r, "PAGE")
    s.first_page_header.paragraphs[0].text = ""
    s.first_page_footer.paragraphs[0].text = ""


def main():
    soup = BeautifulSoup(open(SRC_HTML).read(), "html.parser")
    doc = Document()
    setup(doc)
    doc._body._body.remove(doc.paragraphs[0]._p) if doc.paragraphs else None
    R(doc).blocks(doc, soup.body)
    zoom = doc.settings.element.find(qn("w:zoom"))
    if zoom is not None:
        zoom.set(qn("w:percent"), "100")
    doc.core_properties.title = "ECE 5730 Lab 3 Report: PID Control of a 1D Helicopter"
    doc.core_properties.author = "Amber Li, Ivan Huang, Zarif Karim"
    doc.save(OUT)
    print("wrote", os.path.abspath(OUT))


if __name__ == "__main__":
    main()
