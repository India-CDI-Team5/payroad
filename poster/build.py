"""Inline the figures into poster.html and print it to a 788 x 1091 mm PDF with headless Chrome.

    python poster/make_figs.py     # figures first
    python poster/build.py         # -> poster/out/poster.html, poster/out/payroad_poster.pdf
"""
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "out")
CHROMES = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
]


def svg_body(name):
    with open(os.path.join(HERE, "figs", name + ".svg"), encoding="utf-8") as f:
        s = f.read()
    s = s[s.index("<svg"):]
    s = re.sub(r"<metadata>.*?</metadata>", "", s, flags=re.S)
    # matplotlib clip-path / style ids are per file; prefix them so inlined figures cannot collide
    s = re.sub(r'id="([^"]+)"', lambda m: f'id="{name}-{m.group(1)}"', s)
    s = re.sub(r"url\(#([^)]+)\)", lambda m: f"url(#{name}-{m.group(1)})", s)
    s = re.sub(r'xlink:href="#([^"]+)"', lambda m: f'xlink:href="#{name}-{m.group(1)}"', s)
    s = re.sub(r'(<svg[^>]*?) width="[^"]+" height="[^"]+"', r"\1", s, count=1)   # CSS sets the width
    return s


def build():
    with open(os.path.join(HERE, "poster.html"), encoding="utf-8") as f:
        html = f.read()
    missing = []

    def sub(m):
        name = m.group(1)
        if not os.path.exists(os.path.join(HERE, "figs", name + ".svg")):
            missing.append(name)
            return m.group(0)
        return svg_body(name)

    html = re.sub(r"<!--fig:([a-z_]+)-->", sub, html)
    if missing:
        sys.exit("missing figures: " + ", ".join(missing))
    os.makedirs(OUT, exist_ok=True)
    page = os.path.join(OUT, "poster.html")
    with open(page, "w", encoding="utf-8", newline="\n") as f:
        f.write(html)

    chrome = next((c for c in CHROMES if os.path.exists(c)), None) or shutil.which("chrome")
    print_pdf(chrome, page, os.path.join(OUT, "payroad_poster.pdf"))
    measure(chrome, html)

    # A0 (841 x 1189 mm) for print shops without the 788 x 1091 sheet: lay the same poster out on a
    # 788-wide page that is as tall as A0's aspect ratio, then scale it up by 841/788 so the page is
    # filled edge to edge (columns get the extra height) and every font grows by ~6.7 %.
    s = 841 / 788
    a0 = (html.replace("@page { size: 788mm 1091mm;", "@page { size: 841mm 1189mm;")
              .replace("width: 788mm; height: 1091mm; overflow: hidden;", "width: 841mm; height: 1189mm; overflow: hidden;")
              .replace(".poster { width: 788mm; height: 1091mm;",
                       f".poster {{ transform: scale({s:.6f}); transform-origin: 0 0; width: 788mm; height: {1189 / s:.2f}mm;"))
    assert a0.count("841mm") == 2 and "transform: scale" in a0, "A0 substitutions did not apply"
    page_a0 = os.path.join(OUT, "poster_A0.html")
    with open(page_a0, "w", encoding="utf-8", newline="\n") as f:
        f.write(a0)
    print_pdf(chrome, page_a0, os.path.join(OUT, "payroad_poster_A0.pdf"))
    measure(chrome, a0)


def print_pdf(chrome, page, pdf):
    subprocess.run([chrome, "--headless=new", "--disable-gpu", "--no-pdf-header-footer",
                    "--run-all-compositor-stages-before-draw", "--virtual-time-budget=5000",
                    f"--print-to-pdf={pdf}", "file:///" + page.replace(os.sep, "/")],
                   check=True, capture_output=True)
    print(pdf)


MEASURE_JS = """<script>
addEventListener('load', () => {
  const mm = v => (v * 25.4 / 96).toFixed(1);
  const out = [];
  document.querySelectorAll('.col').forEach((c, i) => {
    const kids = [...c.children], gap = parseFloat(getComputedStyle(c).rowGap);
    const used = kids.reduce((t, k) => t + [...k.children].reduce((u, e) => u + e.getBoundingClientRect().height, 0), 0) + gap * (kids.length - 1);
    out.push(`col${i + 1}: free ${mm(c.getBoundingClientRect().height - used)} mm (overflow if negative)`);
  });
  const small = [...document.querySelectorAll('body *')].filter(e => e.childNodes.length &&
    [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()) &&
    parseFloat(getComputedStyle(e).fontSize) * 25.4 / 96 < 6.95 && !e.closest('svg'));
  out.push('html text under 7 mm: ' + small.length + ' ' + small.slice(0, 5).map(e => e.textContent.trim().slice(0, 20)).join(' | '));
  const pre = document.createElement('pre'); pre.id = 'measure'; pre.textContent = out.join('\\n');
  document.body.appendChild(pre);
});
</script>"""


def measure(chrome, html):
    """Print free space left at the bottom of each column and any HTML text smaller than 7 mm."""
    page = os.path.join(OUT, "_measure.html")
    with open(page, "w", encoding="utf-8", newline="\n") as f:
        f.write(html.replace("</body>", MEASURE_JS + "</body>"))
    r = subprocess.run([chrome, "--headless=new", "--disable-gpu", "--window-size=3200,4500",
                        "--virtual-time-budget=5000", "--dump-dom", "file:///" + page.replace(os.sep, "/")],
                       capture_output=True, text=True, encoding="utf-8")
    os.remove(page)
    m = re.search(r'<pre id="measure">(.*?)</pre>', r.stdout, re.S)
    print(m.group(1) if m else "measure failed")


if __name__ == "__main__":
    build()
