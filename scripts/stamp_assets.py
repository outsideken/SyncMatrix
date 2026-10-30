"""Stamp web/index.html's stylesheet and script links with a hash of their contents.

    python scripts/stamp_assets.py           # rewrite the ?v= stamps in web/index.html
    python scripts/stamp_assets.py --check   # exit 1 if a stamp is out of date

A changed sync_matrix.css or sync_matrix.js gets a new URL
(sync_matrix.css?v=<hash>), so a browser can't pair new code with a cached
old stylesheet after a deploy. Run it after editing either file; the unit
tests fail if a stamp is stale.
"""

import argparse
import hashlib
import re
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[1] / "web"
INDEX = WEB / "index.html"
ASSETS = ("sync_matrix.css", "sync_matrix.js")


def stamp(name: str) -> str:
    return hashlib.sha256((WEB / name).read_bytes()).hexdigest()[:10]


def stamped(html: str) -> str:
    for name in ASSETS:
        html, count = re.subn(r'(["\'])%s(\?v=[0-9a-f]*)?\1' % re.escape(name),
                              r"\g<1>%s?v=%s\g<1>" % (name, stamp(name)), html)
        if count != 1:
            raise SystemExit("index.html should link %s exactly once (found %d)" % (name, count))
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="Only check; exit 1 if a stamp is out of date")
    args = parser.parse_args()
    html = INDEX.read_text()
    new = stamped(html)
    if args.check:
        if new != html:
            print("FAILED: web/index.html asset stamps are out of date; run python scripts/stamp_assets.py")
            return 1
        print("OK: web/index.html asset stamps are current")
        return 0
    INDEX.write_text(new)
    print("Stamped %s" % ", ".join("%s?v=%s" % (n, stamp(n)) for n in ASSETS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
