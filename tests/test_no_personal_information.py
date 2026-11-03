"""No personal information in the repository: it is public, and git keeps history forever.

Scans every tracked text file for email addresses and home-folder paths. The
only addresses allowed are no-reply ones (commit attribution). Things a scan
cannot recognise (names, phone numbers, street addresses, real people's
locations) are covered by the rule in AGENTS.md, not by this test.
"""

import re
import subprocess

from conftest import REPO

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
ALLOWED_EMAIL = re.compile(r"(^|[.@])noreply\b|@users\.noreply\.github\.com$", re.IGNORECASE)
HOME_PATH = re.compile(r"/Users/[^/\s\"']+/|/home/[^/\s\"']+/|[A-Za-z]:\\Users\\[^\\\s\"']+", re.IGNORECASE)


def tracked_text_files():
    names = subprocess.run(["git", "ls-files", "-z"], cwd=REPO, capture_output=True, check=True,
                           text=True).stdout.split("\0")
    for name in filter(None, names):
        path = REPO / name
        if not path.is_file():
            continue
        try:
            yield name, path.read_text()
        except UnicodeDecodeError:
            continue  # binary


def test_no_email_addresses_or_home_paths_are_committed():
    found = []
    for name, text in tracked_text_files():
        found += ["%s: email %s" % (name, m.group()) for m in EMAIL.finditer(text)
                  if not ALLOWED_EMAIL.search(m.group())]
        found += ["%s: home folder %s" % (name, m.group()) for m in HOME_PATH.finditer(text)]
    assert found == [], "personal information in tracked files (see AGENTS.md):\n" + "\n".join(found)


def test_the_scan_catches_what_it_should():
    assert EMAIL.search("contact someone@example.com today")
    assert not ALLOWED_EMAIL.search("someone@example.com")
    assert ALLOWED_EMAIL.search("noreply@anthropic.com")
    assert ALLOWED_EMAIL.search("12345+name@users.noreply.github.com")
    assert HOME_PATH.search("open /Users/someone/Desktop/file")
    assert HOME_PATH.search(r"C:\Users\someone\file")
    assert not EMAIL.search("d3@7.9.0 and @media print")
