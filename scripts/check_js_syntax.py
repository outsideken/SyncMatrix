"""Syntax-check the page's JavaScript with `node --check`.

Covers web/*.js (our own code; vendor/ is skipped) and the inline <script>
blocks in web/*.html. Needs Node.js on PATH. Exit code 1 on any error.
"""

import re
import subprocess
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
INLINE = re.compile(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", re.S | re.I)


def node_check(path: Path, label: str) -> bool:
    result = subprocess.run(["node", "--check", str(path)], capture_output=True, text=True)
    print("%s %s" % ("OK  " if result.returncode == 0 else "FAIL", label))
    if result.returncode:
        print(result.stderr)
    return result.returncode == 0


def main() -> int:
    ok = True
    for js in sorted(WEB.glob("*.js")):
        ok &= node_check(js, js.relative_to(WEB.parent).as_posix())

    with tempfile.TemporaryDirectory() as tmp:
        for html in sorted(WEB.glob("*.html")):
            for i, block in enumerate(INLINE.findall(html.read_text())):
                if not block.strip():
                    continue
                path = Path(tmp) / ("%s.%d.js" % (html.stem, i))
                path.write_text(block)
                ok &= node_check(path, "%s <script> #%d" % (html.relative_to(WEB.parent).as_posix(), i + 1))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
