"""web/index.html loads its stylesheet and script by content hash (scripts/stamp_assets.py)."""

import sys

from conftest import REPO

sys.path.insert(0, str(REPO / "scripts"))
import stamp_assets  # noqa: E402


def test_asset_stamps_are_current():
    # A stale stamp would let a browser keep an old cached stylesheet next to new code.
    html = stamp_assets.INDEX.read_text()
    assert stamp_assets.stamped(html) == html, "run python scripts/stamp_assets.py"
    for name in stamp_assets.ASSETS:
        assert "%s?v=%s" % (name, stamp_assets.stamp(name)) in html
