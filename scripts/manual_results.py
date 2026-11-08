"""Small numeric/text codecs shared by independent instrument report adapters."""
import math
import unicodedata

from manual_tasks import TaskError


def normalized(value):
    value = unicodedata.normalize('NFKC', value).replace('µ', 'u').replace('μ', 'u')
    return ''.join(value.casefold().split()).rstrip(':')


def number(value, decimal_comma=False):
    value = value.strip()
    if not value:
        return None
    if decimal_comma:
        value = value.replace(',', '.')
    try:
        result = float(value)
    except ValueError as error:
        raise TaskError('Invalid numeric result: ' + value) from error
    if not math.isfinite(result):
        raise TaskError('Non-finite numeric result: ' + value)
    return result


def decode_report(content):
    try:
        encoding = 'utf-16' if content.startswith((b'\xff\xfe', b'\xfe\xff')) else 'utf-8-sig'
        text = content.decode(encoding)
    except UnicodeError as error:
        raise TaskError('Report must be UTF-8 or BOM-marked UTF-16') from error
    if '\x00' in text:
        raise TaskError('Unexpected NUL in report')
    return text, encoding
