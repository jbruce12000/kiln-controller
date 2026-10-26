"""The controller exposes a version in the web ui footer, the config
dump, and the config websocket. lib/version.py is the single source of
truth; a tag and the pyproject metadata must agree with it, so these
tests keep the two declarations from drifting apart."""

import os
import re

import version

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def pyproject_version():
    with open(os.path.join(ROOT, "pyproject.toml")) as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
    assert m, "pyproject.toml has no version"
    return m.group(1)


def test_version_is_semver():
    assert re.match(r"^\d+\.\d+\.\d+$", version.__version__), version.__version__


def test_pyproject_version_matches_lib_version():
    # bump both together when releasing (see CONTRIBUTING.md)
    assert pyproject_version() == version.__version__


def test_version_file_has_single_source_of_truth():
    # other code should import lib/version.py, not hardcode the number
    for name in ("kiln-controller.py", "public/assets/js/kiln-controller.js"):
        with open(os.path.join(ROOT, name)) as f:
            assert version.__version__ not in f.read(), (
                "%s hardcodes the version; import/read it instead" % name
            )
