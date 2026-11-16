"""The version in app/version.py must have a CHANGELOG.md entry (commit-git.sh and CI rely on it)."""
import os
import re

from conftest import ROOT
from version import __version__


def test_version_is_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", __version__)


def test_changelog_has_entry_for_version():
    with open(os.path.join(ROOT, "CHANGELOG.md"), encoding="utf-8") as f:
        assert re.search(rf"^## \[{re.escape(__version__)}\] - \d{{4}}-\d{{2}}-\d{{2}}$", f.read(), re.M)


def test_compose_file_holds_no_filled_in_secrets():
    """docker-compose.yml goes to GitHub: keys and passwords are set in the panel, not here."""
    with open(os.path.join(ROOT, "docker-compose.yml"), encoding="utf-8") as f:
        text = f.read()
    assert not re.search(r"(API_KEY|PASSWORD)=\S", text)
    assert "3033:3033" in text and "ghcr.io/<account>/nswhunter" in text
