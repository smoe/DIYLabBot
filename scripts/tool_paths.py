"""Locate the external CAD runtimes used by the generators.

Resolution order for each tool:

1. explicit command-line argument (``--freecad-python`` / ``--solidcraft-cli``),
2. environment variable ``SOLIDCRAFTBOT_FREECAD_PYTHON`` /
   ``SOLIDCRAFTBOT_SOLIDCRAFT_CLI``,
3. ``solidcraft-cli`` on ``PATH`` (SolidCraft only),
4. the usual installation locations on macOS and Windows.

Nothing here pins a machine-specific path into the shared model or build
reports; the resolved executable is a runtime choice of the caller.
"""
from pathlib import Path
import argparse
import os
import shutil
import sys

FREECAD_ENV = "SOLIDCRAFTBOT_FREECAD_PYTHON"
SOLIDCRAFT_ENV = "SOLIDCRAFTBOT_SOLIDCRAFT_CLI"


def _version_key(path):
    """Sort 'FreeCAD 27.1' after 'FreeCAD 9.0' by comparing numeric parts."""
    parts = []
    for token in path.parts[-3].replace("FreeCAD", "").strip().split("."):
        parts.append(int(token) if token.isdigit() else -1)
    return parts


def freecad_candidates(platform=None, environ=None, home=None):
    """Installation locations of FreeCAD's bundled Python, most likely first."""
    platform = platform or sys.platform
    environ = os.environ if environ is None else environ
    home = Path.home() if home is None else Path(home)
    if platform == "darwin":
        bundle = "FreeCAD.app/Contents/Resources/bin/python"
        return [Path("/Applications") / bundle, home / "Applications" / bundle]
    if platform.startswith("win"):
        roots = [Path(environ["LOCALAPPDATA"]) / "Programs"] if environ.get("LOCALAPPDATA") else [home / "AppData/Local/Programs"]
        roots += [Path(environ[key]) for key in ("ProgramFiles", "ProgramFiles(x86)") if environ.get(key)]
        found = []
        for root in roots:
            found += sorted(root.glob("FreeCAD */bin/python.exe"), key=_version_key, reverse=True)
        return found
    # Linux packages usually expose FreeCAD as a module of a system Python;
    # there is no stable bundled interpreter to guess, so require the variable.
    return []


def solidcraft_candidates(platform=None, home=None):
    """Installation locations of the SolidCraft CLI, most likely first."""
    platform = platform or sys.platform
    home = Path.home() if home is None else Path(home)
    if platform == "darwin":
        binary = "SolidCraft.app/Contents/MacOS/solidcraft-cli"
        return [Path("/Applications") / binary, home / "Applications" / binary]
    return []


def _first_existing(paths, exists):
    return next((str(p) for p in paths if exists(p)), None)


def default_freecad_python(platform=None, environ=None, home=None, exists=os.path.exists):
    """Return the FreeCAD Python to use, or None when none can be found."""
    environ = os.environ if environ is None else environ
    if environ.get(FREECAD_ENV):
        return environ[FREECAD_ENV]
    return _first_existing(freecad_candidates(platform, environ, home), exists)


def default_solidcraft_cli(platform=None, environ=None, home=None, exists=os.path.exists, which=shutil.which):
    """Return the SolidCraft CLI to use, or None when none can be found."""
    environ = os.environ if environ is None else environ
    if environ.get(SOLIDCRAFT_ENV):
        return environ[SOLIDCRAFT_ENV]
    return which("solidcraft-cli") or _first_existing(solidcraft_candidates(platform, home), exists)


def add_tool_arguments(parser, freecad=True, solidcraft=True):
    """Add the shared ``--freecad-python`` / ``--solidcraft-cli`` options."""
    if freecad:
        parser.add_argument("--freecad-python", default=None,
                            help="FreeCAD's bundled Python (default: $" + FREECAD_ENV + " or the usual install location)")
    if solidcraft:
        parser.add_argument("--solidcraft-cli", default=None,
                            help="SolidCraft CLI (default: $" + SOLIDCRAFT_ENV + ", PATH or the usual install location)")


def resolve_tool_arguments(parser, args, required=True):
    """Fill unset tool options and fail early with a clear message.

    ``required`` is True (every tool option the parser has), False (none) or
    an iterable of option destinations such as ``{"freecad_python"}`` for
    partial runs like ``--prepare-only``.
    """
    present = [name for name in ("freecad_python", "solidcraft_cli") if name in vars(args)]
    needed = set(present) if required is True else set(required or ())
    lookup = {"freecad_python": (default_freecad_python, "FreeCAD Python", "--freecad-python", FREECAD_ENV),
              "solidcraft_cli": (default_solidcraft_cli, "SolidCraft CLI", "--solidcraft-cli", SOLIDCRAFT_ENV)}
    missing = []
    for name in present:
        finder, label, option, variable = lookup[name]
        setattr(args, name, getattr(args, name) or finder())
        if name in needed and not getattr(args, name):
            missing.append(label + " not found; pass " + option + " or set " + variable)
    if missing:
        parser.error("; ".join(missing))
    return args


def solidcraft_cli():
    """Resolved SolidCraft CLI for scripts without their own option."""
    cli = default_solidcraft_cli()
    if not cli:
        raise SystemExit("SolidCraft CLI not found; set " + SOLIDCRAFT_ENV + " or put solidcraft-cli on PATH")
    return cli


__all__ = ["FREECAD_ENV", "SOLIDCRAFT_ENV", "add_tool_arguments", "default_freecad_python",
           "default_solidcraft_cli", "freecad_candidates", "resolve_tool_arguments",
           "solidcraft_candidates", "solidcraft_cli"]

if __name__ == "__main__":
    report = argparse.ArgumentParser(description="Show the resolved CAD runtimes.")
    report.parse_args()
    print("freecad_python:", default_freecad_python() or "NOT FOUND")
    print("solidcraft_cli:", default_solidcraft_cli() or "NOT FOUND")
