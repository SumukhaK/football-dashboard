"""Football Dashboard Console - Application Package"""

from importlib.metadata import version

# pyproject.toml is the only place the version is written; the installed
# package metadata carries it here, so the two can never disagree.
__version__ = version("football-dashboard")
