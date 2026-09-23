"""Klientens regler for, hvilke stier den synkroniserer.

``RuleSet`` samler reglerne i ``sync_list`` og felterne ``skip_dir``,
``skip_file``, ``skip_dotfiles`` og ``sync_root_files`` fra ``config``.
``includes()`` svarer på, om klienten synkroniserer en sti.

Applikationen tolker ``sync_list`` efter klientens dokumentation i
``/usr/share/doc/onedrive/usage.md.gz``:

- En regel med ``!`` eller ``-`` foran udelukker.
- En regel med ``/`` foran gælder kun fra roden. Andre regler gælder overalt.
- En regel med ``/`` bagerst gælder kun mapper.
- ``*`` gælder inden for ét led. ``**`` gælder over flere led.
- Udelukkelse vinder over inkludering.

En regel gælder den sti, den passer til, og alt under stien. ``X/*`` gælder
også mappen ``X`` selv, som i klienten.

Klienten udelukker lidt mere end dokumentationen for en udelukkende regel
uden ``/`` foran. Den udelukker alle stier, der indeholder reglens tekst.
``RuleSet`` gør det samme. Så kommer en sti, som klienten måske ikke
synkroniserede, ikke i papirkurven.

Sammenligningen i ``sync_list`` er følsom for store og små bogstaver, som i
klienten. ``skip_dir`` og ``skip_file`` er ikke.
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
    """Applikationen kan ikke tolke en regel i ``sync_list``."""

    def __init__(self, rule: str):
        self.rule = rule
        super().__init__(f"Applikationen kan ikke tolke reglen \"{rule}\" i sync_list.")


@dataclass(frozen=True)
class _Rule:
    text: str
    exclude: bool
    rooted: bool
    dir_only: bool
    segments: tuple[str, ...]
    body: str
    """Reglen uden ``!`` eller ``-`` foran."""


def _parse_rule(line: str) -> _Rule | None:
    """Tolk 1 linje. Tomme linjer og kommentarer giver ``None``."""
    text = line.strip()
    if not text or text[0] in "#;":
        return None
    exclude = text[0] in "!-"
    body = text[1:] if exclude else text
    # Klienten afviser selv "/", "/*" og regler med "./" foran.
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
    """Om ``segments`` passer til alle led i ``parts``."""
    if not segments:
        return not parts
    head = segments[0]
    if head == _GLOBBING:
        return any(_match(segments[1:], parts[k:]) for k in range(len(parts) + 1))
    if not parts:
        return False
    return _segment_matches(head, parts[0]) and _match(segments[1:], parts[1:])


def _could_match_below(segments: tuple[str, ...], parts: tuple[str, ...]) -> bool:
    """Om ``segments`` kan passe til ``parts`` eller en sti under ``parts``."""
    if not parts or not segments:
        return True
    if segments[0] == _GLOBBING:
        return True
    return _segment_matches(segments[0], parts[0]) and _could_match_below(segments[1:], parts[1:])


def _hits(rule: _Rule, parts: tuple[str, ...], is_dir: bool) -> bool:
    """Om reglen passer til stien eller til en af dens overmapper."""
    starts = [0] if rule.rooted else range(len(parts))
    for start in starts:
        for end in range(start + 1, len(parts) + 1):
            sub = parts[start:end]
            # Er det kun en overmappe, der passer, er det en mappe.
            folder = is_dir or end < len(parts)
            if _match(rule.segments, sub) and (folder or not rule.dir_only):
                return True
            # "X/*" gælder også mappen X selv.
            if (folder and len(rule.segments) > 1 and rule.segments[-1] == "*"
                    and _match(rule.segments[:-1], sub)):
                return True
    return False


@lru_cache(maxsize=1024)
def _client_regex(body: str) -> re.Pattern:
    return re.compile("".join(".*" if c == "*" else re.escape(c) for c in body))


def _client_excludes(rule: _Rule, parts: tuple[str, ...]) -> bool:
    """Klientens egen, bredere test for en udelukkende regel uden ``/`` foran.

    Klienten fjerner ``/`` og ``*`` bagerst og leder efter teksten i stien.
    Den prøver også reglen som et regulært udtryk, hvor ``*`` er ``.*``.
    """
    path = "/" + "/".join(parts)
    stripped = rule.body.rstrip("/*")
    if stripped and stripped in path:
        return True
    return _client_regex(rule.body.rstrip("/")).search(path) is not None


def is_skipped(rel: str, skip_dirs: Iterable[str], strict: bool = False) -> bool:
    """Om mappen ``rel`` passer til et mønster i ``skip_dir``.

    Et mønster med ``/`` gælder hele stien fra roden. Et mønster uden ``/``
    gælder mappens navn, uanset hvor mappen ligger. Mønstrene er ikke
    følsomme for store og små bogstaver, som i klienten.
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
    """Et mønster fra ``skip_file``. ``*`` og ``?`` gælder alle tegn, som i klienten."""
    text = "".join(".*" if c == "*" else "." if c == "?" else re.escape(c) for c in pattern)
    return re.compile(text, re.IGNORECASE)


class RuleSet:
    """Alle regler, der afgør, om klienten synkroniserer en sti.

    ``folders`` er mappevælgerens mapper uden ``/`` i enderne, eller ``None``,
    hvis ``sync_list`` ikke findes. ``unknown`` er de andre linjer i
    ``sync_list``. En regel, som applikationen ikke kan tolke, giver
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
        # Uden sync_list, eller uden regler i den, synkroniserer klienten alt.
        self._all = not rules
        self._includes = tuple(r for r in rules if not r.exclude)
        self._excludes = tuple(r for r in rules if r.exclude)

    def _filters(self) -> tuple:
        return (self.skip_dirs, self.skip_dir_strict, self.skip_files, self.skip_dotfiles)

    def _filtered(self, parts: tuple[str, ...], is_dir: bool) -> bool:
        """Om ``skip_dotfiles``, ``skip_dir`` eller ``skip_file`` udelukker stien."""
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
        """Om klienten synkroniserer stien ``rel`` direkte.

        En mappe, der kun er en overmappe til en inkluderet sti, tæller ikke.
        Brug ``may_contain()`` til den.
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
        """Om klienten kan synkronisere mappen ``rel`` eller en sti i den."""
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
        """Om ingen sti under mappen ``rel`` går fra ``old`` til ikke at være med her.

        Det gælder, når disse regler inkluderer mappen, og når de ikke
        udelukker mere end ``old``. En sti under mappen, som disse regler
        ikke inkluderer, udelukker ``old`` så også.
        """
        return (self._filters() == old._filters()
                and set(self._excludes) <= set(old._excludes)
                and self.includes(rel, True))
