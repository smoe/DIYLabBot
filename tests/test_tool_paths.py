"""Offline checks for the CAD runtime lookup used by every generator."""
from pathlib import Path
import argparse
import contextlib
import io
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
import json

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import tool_paths  # noqa: E402

NEVER = lambda path: False  # noqa: E731
NO_PATH = lambda name: None  # noqa: E731


class ToolPathTest(unittest.TestCase):
    def test_environment_variable_wins(self):
        env = {tool_paths.FREECAD_ENV: "/opt/fc/python", tool_paths.SOLIDCRAFT_ENV: "/opt/sc/cli"}
        self.assertEqual(tool_paths.default_freecad_python("darwin", env, exists=NEVER), "/opt/fc/python")
        self.assertEqual(tool_paths.default_solidcraft_cli("darwin", env, exists=NEVER, which=lambda n: "/usr/bin/x"), "/opt/sc/cli")

    def test_macos_bundles(self):
        home = Path("/Users/someone")
        fc = tool_paths.default_freecad_python("darwin", {}, home, exists=lambda p: str(p).startswith(str(home)))
        self.assertEqual(fc, str(home / "Applications/FreeCAD.app/Contents/Resources/bin/python"))
        sc = tool_paths.default_solidcraft_cli("darwin", {}, home, exists=lambda p: True, which=NO_PATH)
        self.assertEqual(sc, "/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli")

    def test_path_before_bundle(self):
        self.assertEqual(tool_paths.default_solidcraft_cli("darwin", {}, exists=lambda p: True, which=lambda n: "/bin/solidcraft-cli"), "/bin/solidcraft-cli")

    def test_windows_picks_newest_freecad(self):
        with tempfile.TemporaryDirectory() as tmp:
            for version in ["FreeCAD 9.0", "FreeCAD 27.1", "FreeCAD 1.0"]:
                exe = Path(tmp) / "Programs" / version / "bin/python.exe"
                exe.parent.mkdir(parents=True)
                exe.write_text("")
            found = tool_paths.default_freecad_python("win32", {"LOCALAPPDATA": tmp}, Path(tmp))
            self.assertEqual(Path(found).parts[-3], "FreeCAD 27.1")

    def test_linux_requires_explicit_freecad(self):
        self.assertIsNone(tool_paths.default_freecad_python("linux", {}, exists=lambda p: True))

    def test_resolve_reports_missing_tools(self):
        parser = argparse.ArgumentParser()
        tool_paths.add_tool_arguments(parser)
        args = parser.parse_args(["--freecad-python", "/x/python", "--solidcraft-cli", "/x/cli"])
        self.assertEqual(vars(tool_paths.resolve_tool_arguments(parser, args)), {"freecad_python": "/x/python", "solidcraft_cli": "/x/cli"})
        original = tool_paths.default_solidcraft_cli
        tool_paths.default_solidcraft_cli = lambda: None
        try:
            args = parser.parse_args(["--freecad-python", "/x/python"])
            tool_paths.resolve_tool_arguments(parser, args, required={"freecad_python"})
            self.assertIsNone(args.solidcraft_cli)
            with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()) as err:
                tool_paths.resolve_tool_arguments(parser, parser.parse_args(["--freecad-python", "/x/python"]))
            self.assertIn(tool_paths.SOLIDCRAFT_ENV, err.getvalue())
        finally:
            tool_paths.default_solidcraft_cli = original

    def test_gallery_check_does_not_require_a_cad_runtime(self):
        import render_model_gallery as gallery
        with patch.object(sys,'argv',['gallery','--check']),patch.object(tool_paths,'default_solidcraft_cli',return_value=None),patch.object(gallery,'check') as check:
            gallery.main()
        check.assert_called_once()

    def test_pickup_prepare_does_not_require_runtimes(self):
        import build_centrifuge_robot_pickup as builder
        # Stop immediately after argument resolution; no generated files are touched.
        class Resolved(Exception):pass
        resolve=tool_paths.resolve_tool_arguments
        def inspected(parser,args,required=True):
            resolve(parser,args,required)
            self.assertFalse(required);self.assertIsNone(args.freecad_python);self.assertIsNone(args.solidcraft_cli)
            raise Resolved()
        with patch.object(sys,'argv',['pickup','--prepare-only']),patch.object(tool_paths,'default_freecad_python',return_value=None),patch.object(tool_paths,'default_solidcraft_cli',return_value=None),patch.object(tool_paths,'resolve_tool_arguments',side_effect=inspected),self.assertRaises(Resolved):builder.main()

    def test_native_pickup_explicit_option_then_context_then_shared_lookup(self):
        import export_centrifuge_robot_pickup_solidcraft as exporter
        class Resolved(Exception):pass
        for explicit,context,expected in [('/explicit','/context','/explicit'),(None,'/context','/context'),(None,None,'/shared')]:
            def inspected(parser,args,required=True):
                self.assertEqual(args.solidcraft_cli,expected)
                raise Resolved()
            with tempfile.TemporaryDirectory() as tmp:
                path=Path(tmp)/'context.json';path.write_text(json.dumps({'solidcraft_cli':context}))
                argv=['exporter','--context',str(path)]+(['--solidcraft-cli',explicit] if explicit else [])
                with patch.object(sys,'argv',argv),patch.object(tool_paths,'solidcraft_cli',return_value='/shared') as lookup,patch.object(tool_paths,'resolve_tool_arguments',side_effect=inspected),self.assertRaises(Resolved):exporter.main()
                self.assertEqual(lookup.call_count,1 if explicit is None and context is None else 0)

    def test_generators_have_no_machine_specific_defaults(self):
        pattern = re.compile(r"AppData|Program Files|FreeCAD 27\.1/bin|/Applications/")
        offenders = [p.name for p in (ROOT / "scripts").rglob("*.py")
                     if p.name != "tool_paths.py" and pattern.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])


if __name__ == "__main__":
    unittest.main()
