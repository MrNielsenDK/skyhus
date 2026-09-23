"""The client's rules for which paths it syncs.

``RuleSet`` collects the rules in ``sync_list`` and the fields ``skip_dir``,
``skip_file``, ``skip_dotfiles`` and ``sync_root_files`` from ``config``.
``includes()`` tells if the client syncs a path.

The application interprets ``sync_list`` as the client's documentation in
``/usr/share/doc/onedrive/usage.md.gz`` describes:

- A rule with a leading ``!`` or ``-`` excludes.
- A rule with a leading ``/`` applies only from the root. Other rules apply anywhere.
- A rule with a trailing ``/`` applies only to folders.
- ``*`` applies within one segment. ``**`` applies across several segments.
- Exclusion wins over inclusion.

A rule applies to the path it matches and to everything below that path.
``X/*`` also applies to the folder ``X`` itself, as in the client.

The client excludes a bit more than the documentation says for an excluding
rule without a leading ``/``. It excludes all paths that contain the text of
the rule. ``RuleSet`` does the same. Then a path that the client maybe did not
sync does not go to Trash.

The comparison in ``sync_list`` is case-sensitive, as in the client.
``skip_dir`` and ``skip_file`` are not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fnmatch import fnmatchcase
from functools import lru_cache
from typing import Iterable

from .config import DEFAULT_SKIP_FILE

DEFAULT_SKIP_FILES = tuple(DEFAULT_SKIP_FILE.split("|"))
_GLOBBING = "**"


class UnknownRuleError(ValueError):
    """The application cannot interpret a rule in ``sync_list``."""

    def __init__(self, rule: str):
        self.rule = rule
        super().__init__(f"Skyhus cannot interpret the rule \"{rule}\" in sync_list.")


@dataclass(frozen=True)
class _Rule:
    text: str
    exclude: bool
    rooted: bool
    dir_only: bool
    segments: tuple[str, ...]
    body: str
    """The rule without the leading ``!`` or ``-``."""


def _parse_rule(line: str) -> _Rule | None:
    """Interpret 1 line. Empty lines and comments give ``None``."""
    text = line.strip()
    if not text or text[0] in "#;":
        return None
    exclude = text[0] in "!-"
    body = text[1:] if exclude else text
    # The client itself rejects "/", "/*" and rules with a leading "./".
    if body in ("", "/", "/*") or body.startswith("./"):
        raise UnknownRuleError(text)
    rooted = body.startswith("/")
    dir_only = body.endswith("/")
    inner = body[1:] if rooted else body
    inner = inner[:-1] if dir_only else inner
    segments = tuple(inner.split("/"))
    for segment in segments:
        if segment in ("", ".", ".."):
            raise UnknownRuleError(text)
        if _GLOBBING in segment and segment != _GLOBBING:
            raise UnknownRuleError(text)
    return _Rule(text, exclude, rooted, dir_only, segments, body)


@lru_cache(maxsize=4096)
def _segment_regex(pattern: str) -> re.Pattern:
    return re.compile("".join(".*" if c == "*" else re.escape(c) for c in pattern))


def _segment_matches(pattern: str, name: str) -> bool:
    if "*" not in pattern:
        return pattern == name
    return _segment_regex(pattern).fullmatch(name) is not None


def _match(segments: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    """Whether ``segments`` matches all segments in ``parts``."""
    if not segments:
        return not parts
    head = segments[0]
    if head == _GLOBBING:
        return any(_match(segments[1:], parts[k:]) for k in range(len(parts) + 1))
    if not parts:
        return False
    return _segment_matches(head, parts[0]) and _match(segments[1:], parts[1:])


def _could_match_below(segments: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    """Whether ``segments`` can match ``parts`` or a path below ``parts``."""
    if not parts or not segments:
        return True
    if segments[0] == _GLOBBING:
        return True
    return _segment_matches(segments[0], parts[0]) and _could_match_below(segments[1:], parts[1:])


def _hits(rule: _Rule, parts: tuple[str, ...], is_dir: bool) -> bool:
    """Whether the rule matches the path or one of its parent folders."""
    starts = [0] if rule.rooted else range(len(parts))
    for start in starts:
        for end in range(start + 1, len(parts) + 1):
            sub = parts[start:end]
            # If only a parent folder matches, it is a folder.
            folder = is_dir or end < len(parts)
            if _match(rule.segments, sub) and (folder or not rule.dir_only):
                return True
            # "X/*" also applies to the folder X itself.
            if (folder and len(rule.segments) > 1 and rule.segments[-1] == "*"
                    and _match(rule.segments[:-1], sub)):
                return True
    return False


@lru_cache(maxsize=1024)
def _client_regex(body: str) -> re.Pattern:
    return re.compile("".join(".*" if c == "*" else re.escape(c) for c in body))


def _client_excludes(rule: _Rule, parts: tuple[str, ...]) -> bool:
    """The client's own, wider test for an excluding rule without a leading ``/``.

    The client removes the trailing ``/`` and ``*`` and looks for the text in the path.
    It also tries the rule as a regular expression where ``*`` is ``.*``.
    """
    path = "/" + "/".join(parts)
    stripped = rule.body.rstrip("/*")
    if stripped and stripped in path:
        return True
    return _client_regex(rule.body.rstrip("/")).search(path) is not None


def is_skipped(rel: str, skip_dirs: Iterable[str], strict: bool = False) -> bool:
    """Whether the folder ``rel`` matches a pattern in ``skip_dir``.

    A pattern with ``/`` applies to the full path from the root. A pattern
    without ``/`` applies to the folder name, wherever the folder is. The
    patterns are not case-sensitive, as in the client.
    """
    rel_cf = rel.casefold()
    name_cf = rel_cf.rsplit("/", 1)[-1]
    for pattern in skip_dirs:
        pattern_cf = pattern.strip().casefold()
        if not pattern_cf:
            continue
        if "/" in pattern_cf or strict:
            if fnmatchcase(rel_cf, pattern_cf.strip("/")):
                return True
        elif fnmatchcase(name_cf, pattern_cf):
            return True
    return False


@lru_cache(maxsize=1024)
def _wildcard_regex(pattern: str) -> re.Pattern:
    """A pattern from ``skip_file``. ``*`` and ``?`` match all characters, as in the client."""
    text = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.compile(text, re.IGNORECASE)


class RuleSet:
    """All rules that decide if the client syncs a path.

    ``folders`` are the folders from the folder picker without ``/`` at the ends,
    or ``None`` if ``sync_list`` does not exist. ``unknown`` are the other lines
    in ``sync_list``. A rule that the application cannot interpret gives
    ``UnknownRuleError``.
    """

    def __init__(self, folders: list[str] | None, root_files: bool = False,
                 unknown: Iterable[str] = (), *, skip_dirs: Iterable[str] = (),
                 skip_dir_strict: bool = False, skip_files: Iterable[str] | None = None,
                 skip_dotfiles: bool = False):
        self.root_files = root_files
        self.skip_dirs = tuple(p.strip() for p in skip_dirs if p.strip())
        self.skip_dir_strict = skip_dir_strict
        self.skip_files = tuple(p.strip() for p in (DEFAULT_SKIP_FILES if skip_files is None else skip_files)
                                if p.strip())
        self.skip_dotfiles = skip_dotfiles
        rules: list[_Rule] = []
        if folders is not None:
            for line in [*unknown, *(f"/{folder}/" for folder in folders)]:
                rule = _parse_rule(line)
                if rule is not None:
                    rules.append(rule)
        # Without sync_list, or without rules in it, the client syncs everything.
        self._all = not rules
        self._includes = tuple(r for r in rules if not r.exclude)
        self._excludes = tuple(r for r in rules if r.exclude)

    def _filters(self) -> tuple:
        return (self.skip_dirs, self.skip_dir_strict, self.skip_files, self.skip_dotfiles)

    def _filtered(self, parts: tuple[str, ...], is_dir: bool) -> bool:
        """Whether ``skip_dotfiles``, ``skip_dir`` or ``skip_file`` excludes the path."""
        if self.skip_dotfiles and any(part.startswith(".") for part in parts):
            return True
        if self.skip_dirs:
            depth = len(parts) if is_dir else len(parts) - 1
            for k in range(1, depth + 1):
                if is_skipped("/".join(parts[:k]), self.skip_dirs, self.skip_dir_strict):
                    return True
        if not is_dir and self.skip_files:
            rel = "/".join(parts)
            for candidate in (rel, "/" + rel, parts[-1]):
                if any(_wildcard_regex(p).fullmatch(candidate) for p in self.skip_files):
                    return True
        return False

    def _excluded(self, parts: tuple[str, ...], is_dir: bool) -> bool:
        for rule in self._excludes:
            if _hits(rule, parts, is_dir):
                return True
            if not rule.rooted and _client_excludes(rule, parts):
                return True
        return False

    def includes(self, rel: str, is_dir: bool) -> bool:
        """Whether the client syncs the path ``rel`` directly.

        A folder that is only a parent folder of an included path does not count.
        Use ``may_contain()`` for that.
        """
        parts = tuple(rel.split("/"))
        if self._filtered(parts, is_dir):
            return False
        if self._all:
            return True
        if self._excluded(parts, is_dir):
            return False
        if not is_dir and len(parts) == 1 and self.root_files:
            return True
        return any(_hits(rule, parts, is_dir) for rule in self._includes)

    def may_contain(self, rel: str) -> bool:
        """Whether the client can sync the folder ``rel`` or a path in it."""
        parts = tuple(rel.split("/"))
        if self._filtered(parts, True):
            return False
        if self._all:
            return True
        if self._excluded(parts, True):
            return False
        return any(not rule.rooted or _could_match_below(rule.segments, parts)
                   for rule in self._includes)

    def keeps_all_below(self, rel: str, old: RuleSet) -> bool:
        """Whether no path below the folder ``rel`` goes from included in ``old`` to not included here.

        This is true when these rules include the folder and do not exclude
        more than ``old``. A path below the folder that these rules do not
        include is then also excluded by ``old``.
        """
        return (self._filters() == old._filters()
                and set(self._excludes) <= set(old._excludes)
                and self.includes(rel, True))
