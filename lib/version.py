"""The running version of the kiln controller.

This is the single source of truth for the version shown in the web
ui footer, in the config dump, and on the config websocket. Bump it
together with `version` in pyproject.toml and tag the release -- see
the "Releasing" section of CONTRIBUTING.md. A test keeps the two in
sync so they cannot drift apart.
"""

__version__ = "2.0.0"
