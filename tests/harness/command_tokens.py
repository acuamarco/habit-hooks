from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .command_model import Word


class TokenKind(Enum):
    WORD = "WORD"
    PIPE = "PIPE"
    AND_IF = "AND_IF"
    SEMI = "SEMI"
    NEWLINE = "NEWLINE"
    REDIR_IN = "REDIR_IN"
    REDIR_OUT = "REDIR_OUT"
    REDIR_APPEND = "REDIR_APPEND"
    FD_DUP = "FD_DUP"
    EOF = "EOF"


@dataclass(frozen=True)
class Token:
    kind: TokenKind
    value: Word | tuple[int, int] | int | None
    start: int
    end: int


OPERATORS = {
    "&&": TokenKind.AND_IF,
    "|": TokenKind.PIPE,
    ";": TokenKind.SEMI,
    "<": TokenKind.REDIR_IN,
    ">>": TokenKind.REDIR_APPEND,
    ">": TokenKind.REDIR_OUT,
}
ESCAPABLE = "\\'\"$|&;<>"
