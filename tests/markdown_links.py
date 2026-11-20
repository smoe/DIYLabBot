"""Offline relative Markdown/HTML link validation; no CAD or network required."""
from collections import Counter
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
import re
import unicodedata
from urllib.parse import unquote, urlsplit


def prose(text):
    """Keep line positions while excluding fenced code and HTML comments."""
    text = re.sub(r'<!--.*?-->', lambda m: '\n' * m[0].count('\n'), text, flags=re.S)
    lines, fence = [], None
    for line in text.splitlines():
        mark = re.match(r'^ {0,3}(`{3,}|~{3,})', line)
        if mark and fence is None:
            fence = (mark[1][0], len(mark[1]))
            lines.append('')
        elif fence:
            if re.match(r'^ {0,3}' + re.escape(fence[0]) + '{' + str(fence[1]) + r',}\s*$', line):
                fence = None
            lines.append('')
        else:
            lines.append(line)
    return lines


class HTMLReferences(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.anchors, self.links = set(), []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get('id'):
            self.anchors.add(attrs['id'])
        if tag == 'a' and attrs.get('name'):
            self.anchors.add(attrs['name'])
        for key in ('href', 'src'):
            if attrs.get(key):
                self.links.append((self.getpos()[0], attrs[key]))

    handle_startendtag = handle_starttag


def slug(title):
    title = re.sub(r'<[^>]+>', '', title)
    title = re.sub(r'!?\[([^\]]+)\]\([^)]*\)', r'\1', title)
    title = unescape(title).lower()
    return ''.join(c for c in title if c in ' -_' or unicodedata.category(c)[0] in 'LN').replace(' ', '-')


def anchors(text):
    lines = prose(text)
    html = HTMLReferences()
    html.feed('\n'.join(lines))
    result, counts = set(html.anchors), Counter()
    for i, line in enumerate(lines):
        match = re.match(r'^ {0,3}#{1,6}\s+(.+?)\s*#*\s*$', line)
        title = match[1] if match else None
        if i + 1 < len(lines) and line.strip() and re.fullmatch(r' {0,3}(?:=+|-+)\s*', lines[i + 1]):
            title = line.strip()
        if title is not None:
            base = slug(title)
            name = base
            while name in counts:
                counts[base] += 1
                name = base + '-' + str(counts[base])
            counts[name] = 0
            result.add(name)
    return result


def inline_links(line):
    """Parse balanced destinations, including images and escaped parentheses."""
    start = 0
    while True:
        match = re.search(r'!?\[(?:\\.|[^\]\\])*\]\(', line[start:])
        if not match:
            return
        cursor = start + match.end()
        first = cursor
        if cursor < len(line) and line[cursor] == '<':
            end = line.find('>', cursor + 1)
            if end < 0:
                return
            yield line[cursor + 1:end]
            start = end + 1
            continue
        depth = 0
        while cursor < len(line):
            char = line[cursor]
            if char == '\\':
                cursor += 2
                continue
            if char == '(':
                depth += 1
            elif char == ')':
                if depth == 0:
                    break
                depth -= 1
            elif char.isspace() and depth == 0:
                break
            cursor += 1
        if cursor > first:
            yield re.sub(r'\\([()])', r'\1', line[first:cursor])
        start = max(cursor + 1, first + 1)


def links(text):
    lines = prose(text)
    definitions = {}
    for line in lines:
        match = re.match(r'^ {0,3}\[([^\]]+)\]:\s*(<[^>]+>|\S+)', line)
        if match:
            definitions[' '.join(match[1].casefold().split())] = match[2].strip('<>')
    for number, line in enumerate(lines, 1):
        # Inline code is an example or path mention, not a rendered link.
        line = re.sub(r'(`+).*?\1', '', line)
        definition = re.match(r'^ {0,3}\[([^\]]+)\]:', line)
        if definition:
            key = ' '.join(definition[1].casefold().split())
            yield number, definitions[key]
            continue
        for raw in inline_links(line):
            yield number, raw
        for match in re.finditer(r'!?\[([^\]]+)\](?:\[([^\]]*)\])?(?![\[(])', line):
            key = ' '.join((match[2] or match[1]).casefold().split())
            if key in definitions:
                yield number, definitions[key]
        parser = HTMLReferences()
        parser.feed(line)
        for _, raw in parser.links:
            yield number, raw


def check(root, documents, ignored=()):
    """Return errors and explicitly classified optional local build links.

    Missing ignored artifacts are not required in a fresh clone. Ignored targets
    are recorded separately, never presented as validated artifacts.
    """
    root = Path(root).resolve()
    ignored = set(ignored)
    errors, optional, cache = [], [], {}
    for source in documents:
        text = (root / source).read_text(encoding='utf-8')
        # The gallery template is rendered at docs/models/README.md.
        context = 'docs/models/README.md' if source == 'scripts/templates/model_gallery.md' else source
        for line, raw in links(text):
            raw = unescape(raw)
            try:
                url = urlsplit(raw)
            except ValueError:
                errors.append(f'{source}:{line}: invalid destination {raw!r}')
                continue
            if url.scheme or raw.startswith('//'):
                continue
            path = unquote(url.path)
            target = (root / path.lstrip('/')) if path.startswith('/') else (root / context).parent / path
            if not path:
                target = root / context
            target = target.resolve()
            try:
                relative = target.relative_to(root).as_posix()
            except ValueError:
                errors.append(f'{source}:{line}: target escapes repository: {raw}')
                continue
            if relative in ignored:
                optional.append(f'{source}:{line}: optional ignored output {raw}')
                continue
            if not target.exists():
                errors.append(f'{source}:{line}: missing target {raw}')
                continue
            fragment = unquote(url.fragment)
            if fragment and target.suffix.lower() in {'.md', '.html', '.htm'}:
                if target not in cache:
                    target_text = target.read_text(encoding='utf-8')
                    if target.suffix.lower() == '.md':
                        cache[target] = anchors(target_text)
                    else:
                        parser = HTMLReferences()
                        parser.feed(target_text)
                        cache[target] = parser.anchors
                if fragment not in cache[target]:
                    errors.append(f'{source}:{line}: missing anchor {raw}')
    return errors, optional
