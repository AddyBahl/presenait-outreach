#!/usr/bin/env python3
"""
Builds the GitHub Pages demo into ../docs from the real dashboard page.

  python demo/build_demo.py

Run it again whenever you change static/index.html or demo/demo.js, then commit
and push the docs folder. GitHub Pages serves docs/ at
https://addybahl.github.io/presenait-outreach/
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"

page = (ROOT / "static" / "index.html").read_text()
if "</head>" not in page:
    raise SystemExit("static/index.html has no </head> tag")
page = page.replace("</head>", '<script src="demo.js"></script>\n</head>', 1)
page = page.replace("<title>PresenAIT Outreach</title>", "<title>PresenAIT Outreach (demo)</title>", 1)

DOCS.mkdir(exist_ok=True)
(DOCS / "index.html").write_text(page)
(DOCS / "demo.js").write_text((ROOT / "demo" / "demo.js").read_text())
(DOCS / ".nojekyll").write_text("")  # serve files as-is
print(f"Demo built in {DOCS}")
