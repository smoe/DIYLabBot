"""Repository link gate and small independent Markdown/HTML fixtures."""
from pathlib import Path
import subprocess
import tempfile
import unittest

from markdown_links import anchors, check, links


class MarkdownLinkTests(unittest.TestCase):
    def test_unicode_formatting_and_duplicate_heading_ids(self):
        self.assertEqual(anchors('# **Größe** & `Maße`\n# Größe & Maße\n# Größe & Maße-1\n'),
                         {'größe--maße', 'größe--maße-1', 'größe--maße-1-1'})

    def test_setext_and_explicit_html_anchors_ignore_code(self):
        text = 'Titel\n=====\n<a id="stable"></a>\n~~~html\n<h2 id="example">x</h2>\n~~~\n'
        self.assertEqual(anchors(text), {'titel', 'stable'})

    def test_inline_images_references_and_balanced_paths(self):
        text = '[one](a(b).md#x) ![image](<a b.png>)\n[full][ref] [ref][] [ref]\n[ref]: target.md "Title"\n'
        found = [raw for _, raw in links(text)]
        self.assertIn('a(b).md#x', found)
        self.assertIn('a b.png', found)
        self.assertEqual(found.count('target.md'), 4)

    def test_examples_comments_and_external_links(self):
        text = '`[code](absent.md)`\n```md\n[code](absent.md)\n```\n<!-- [x](absent.md) -->\n[web](https://example.org/a)\n'
        self.assertEqual(list(links(text)), [(6, 'https://example.org/a')])

    def test_reports_missing_anchor_and_path_but_accepts_encoded_spaces(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'a b.md').write_text('# Größe\n', encoding='utf-8')
            (root / 'README.md').write_text('[ok](a%20b.md#gr%C3%B6%C3%9Fe)\n[no](a%20b.md#missing)\n[absent](missing.md)\n', encoding='utf-8')
            errors, optional = check(root, ['README.md'])
            self.assertEqual(len(errors), 2)
            self.assertIn('missing anchor', errors[0])
            self.assertIn('missing target', errors[1])
            self.assertEqual(optional, [])

    def test_html_links_and_fragments_are_checked(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'page.html').write_text('<a name="old"></a><div id="new"></div>')
            (root / 'README.md').write_text('<a href="page.html#old">ok</a>\n<img src="missing.png">\n')
            errors, _ = check(root, ['README.md'])
            self.assertEqual(len(errors), 1)
            self.assertIn('missing.png', errors[0])

    def test_generated_outputs_are_reported_separately_from_broken_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'README.md').write_text('[local](exports/report.json)\n[broken](docs/missing.md)\n')
            errors, optional = check(root, ['README.md'], ignored=['exports/report.json'])
            self.assertEqual(len(errors), 1)
            self.assertEqual(len(optional), 1)
            self.assertIn('docs/missing.md', errors[0])

    def test_template_uses_gallery_output_context(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'scripts/templates').mkdir(parents=True)
            (root / 'docs/models').mkdir(parents=True)
            (root / 'scripts/templates/model_gallery.md').write_text('[proof](provenance.json)\n')
            (root / 'docs/models/provenance.json').write_text('{}')
            self.assertEqual(check(root, ['scripts/templates/model_gallery.md']), ([], []))

    def test_repository_relative_links(self):
        root = Path(__file__).resolve().parents[1]
        tracked = subprocess.check_output(['git', 'ls-files', '-z'], cwd=root).decode().split('\0')
        documents = [p for p in tracked if p.endswith('.md') and (root / p).is_file()]
        # Ask Git once; the same ignore policy defines optional local build files.
        candidates = set()
        from urllib.parse import unquote, urlsplit
        for source in documents:
            context = 'docs/models/README.md' if source == 'scripts/templates/model_gallery.md' else source
            for _, raw in links((root / source).read_text(encoding='utf-8')):
                try:
                    url = urlsplit(raw)
                    if url.scheme or raw.startswith('//'):
                        continue
                    path = unquote(url.path)
                    dest = root / path.lstrip('/') if path.startswith('/') else (root / context).parent / path
                    candidates.add(dest.resolve().relative_to(root).as_posix())
                except ValueError:
                    continue  # check() will report malformed/escaping destinations.
        result = subprocess.run(['git', 'check-ignore', '--no-index', '--stdin'], cwd=root,
                                input='\n'.join(sorted(candidates))+'\n', text=True, capture_output=True)
        self.assertIn(result.returncode, (0, 1), result.stderr)
        errors, optional = check(root, documents, ignored=result.stdout.splitlines())
        self.assertEqual(errors, [], '\n'.join(errors))
        self.assertTrue(documents)


if __name__ == '__main__':
    unittest.main()
