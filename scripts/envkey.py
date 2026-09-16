#!/usr/bin/env python3
"""API key lookup for every script in this pipeline.

Resolution order (first hit wins):
  1. the process environment
  2. a dotenv-style file named by $CLIP_FACTORY_ENV
  3. ./.env in the current working directory
  4. ~/.clip-factory.env

The file format is plain `KEY=value`, one per line; surrounding quotes and
`export ` prefixes are stripped, `#` comments and blank lines are ignored.
Nothing is ever written back, and no key is printed.
"""
import os

_CACHE = None


def _candidates():
    named = os.environ.get('CLIP_FACTORY_ENV')
    if named:
        yield os.path.expanduser(named)
    yield os.path.join(os.getcwd(), '.env')
    yield os.path.expanduser('~/.clip-factory.env')


def _dotenv():
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    _CACHE = {}
    for path in _candidates():
        if not path or not os.path.exists(path):
            continue
        try:
            with open(path) as fh:
                for line in fh:
                    line = line.strip()
                    if not line or line.startswith('#') or '=' not in line:
                        continue
                    if line.startswith('export '):
                        line = line[len('export '):]
                    k, v = line.split('=', 1)
                    _CACHE.setdefault(k.strip(), v.strip().strip('"').strip("'"))
        except OSError:
            continue
    return _CACHE


def get_key(*names, required=True):
    """Return the first non-empty value among `names`, or exit with a clear message."""
    env = _dotenv()
    for n in names:
        v = os.environ.get(n) or env.get(n)
        if v:
            return v
    if not required:
        return None
    raise SystemExit(
        'Missing API key: set one of ' + ', '.join(names) + ' in the environment, '
        'or put it in .env / ~/.clip-factory.env (see .env.example).')
