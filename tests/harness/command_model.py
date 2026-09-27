from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


@dataclass(frozen=True)
class SourceSpan:
    source: str
    line: int
    column: int = 1


class CommandPlatform(Enum):
    POSIX = "posix"
    WINDOWS = "windows"


@dataclass(frozen=True)
class Literal:
    value: str


@dataclass(frozen=True)
class Variable:
    name: str


@dataclass(frozen=True)
class Word:
    parts: tuple[Literal | Variable, ...]


@dataclass(frozen=True)
class Assignment:
    name: str
    value: Word


class RedirectionKind(Enum):
    INPUT = "<"
    OUTPUT = ">"
    APPEND = ">>"
    DUPLICATE = "duplicate"


@dataclass(frozen=True)
class Redirection:
    descriptor: int
    kind: RedirectionKind
    target: Word | int


@dataclass(frozen=True)
class SimpleCommand:
    assignments: tuple[Assignment, ...]
    argv: tuple[Word, ...]
    redirections: tuple[Redirection, ...]
    source: SourceSpan


@dataclass(frozen=True)
class Pipeline:
    commands: tuple[SimpleCommand, ...]


@dataclass(frozen=True)
class AndChain:
    pipelines: tuple[Pipeline, ...]


@dataclass(frozen=True)
class Script:
    chains: tuple[AndChain, ...]
