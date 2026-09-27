from __future__ import annotations

from .command_model import Literal, SourceSpan, Variable, Word
from .command_tokens import ESCAPABLE, OPERATORS, Token, TokenKind
from .errors import SpecError


def lex(script: str, source: SourceSpan = SourceSpan("<inline>", 1)) -> tuple[Token, ...]:
    return _Lexer(script, source).run()


class _Lexer:
    def __init__(self, script: str, source: SourceSpan):
        self.script = script
        self.source = source
        self.tokens: list[Token] = []
        self.parts: list[Literal | Variable] = []
        self.word_start: int | None = None
        self.i = 0

    def fail(self, message: str, offset: int) -> None:
        line_start = self.script.rfind("\n", 0, offset) + 1
        line_end = self.script.find("\n", offset)
        line_end = len(self.script) if line_end < 0 else line_end
        line = self.script[line_start:line_end]
        line_no = self.source.line + self.script[:offset].count("\n")
        column = offset - line_start + 1
        raise SpecError(f"{self.source.source}:{line_no}:{column}: {message}\n{line}\n{' ' * (column - 1)}^")

    def flush(self, end: int) -> None:
        if self.word_start is not None:
            self.tokens.append(Token(TokenKind.WORD, Word(tuple(self.parts)), self.word_start, end))
            self.word_start, self.parts = None, []

    def literal(self, value: str) -> None:
        if self.parts and isinstance(self.parts[-1], Literal):
            self.parts[-1] = Literal(self.parts[-1].value + value)
        else:
            self.parts.append(Literal(value))

    def variable(self) -> None:
        if self.script.startswith("${", self.i):
            self.braced_variable()
        else:
            self.named_variable()

    def braced_variable(self) -> None:
        at = self.i
        close = self.script.find("}", at + 2)
        name = self.script[at + 2 : close] if close >= 0 else ""
        valid = name and (name[0].isalpha() or name[0] == "_") and all(c.isalnum() or c == "_" for c in name)
        if not valid:
            self.fail("invalid variable expansion", at)
        self.parts.append(Variable(name))
        self.i = close + 1

    def named_variable(self) -> None:
        end = self.i + 1
        if end < len(self.script) and (self.script[end].isalpha() or self.script[end] == "_"):
            while end < len(self.script) and (self.script[end].isalnum() or self.script[end] == "_"):
                end += 1
            self.parts.append(Variable(self.script[self.i + 1 : end]))
            self.i = end
        else:
            self.literal("$")
            self.i += 1

    def operator(self) -> bool:
        if self.word_start is not None:
            return False
        return self.fd_dup() or self.numeric_redirection() or self.simple_operator()

    def fd_dup(self) -> bool:
        for spelling in ("2>&1", "1>&2", ">&2"):
            if self.script.startswith(spelling, self.i):
                fds = (2, 1) if spelling == "2>&1" else (1, 2)
                self.tokens.append(Token(TokenKind.FD_DUP, fds, self.i, self.i + len(spelling)))
                self.i += len(spelling)
                return True
        return False

    def numeric_redirection(self) -> bool:
        i, s = self.i, self.script
        if not s[i].isdigit() or i + 1 >= len(s) or s[i + 1] not in "><":
            return False
        if s[i] not in "012":
            self.fail("unsupported file descriptor", i)
        if s.startswith(">&", i + 1):
            self.fail("unsupported descriptor duplication", i)
        op = ">>" if s.startswith(">>", i + 1) else ">"
        kind = TokenKind.REDIR_APPEND if op == ">>" else TokenKind.REDIR_OUT
        self.tokens.append(Token(kind, int(s[i]), i, i + len(op) + 1))
        self.i += len(op) + 1
        return True

    def simple_operator(self) -> bool:
        i, s = self.i, self.script
        op = "&&" if s.startswith("&&", i) else ">>" if s.startswith(">>", i) else s[i]
        if op not in OPERATORS:
            if s[i] == "&":
                self.fail("unsupported shell operator", i)
            return False
        self.tokens.append(Token(OPERATORS[op], None, i, i + len(op)))
        self.i += len(op)
        return True

    def quoted(self) -> None:
        if self.script[self.i] == "'":
            self.single_quote()
        else:
            self.double_quote()

    def single_quote(self) -> None:
        end = self.script.find("'", self.i + 1)
        if end < 0:
            self.fail("unterminated single quote", self.i)
        self.literal(self.script[self.i + 1 : end])
        self.i = end + 1

    def double_quote(self) -> None:
        start = self.word_start
        self.i += 1
        while self.i < len(self.script) and self.script[self.i] != '"':
            self.double_quote_character()
        if self.i >= len(self.script):
            self.fail("unterminated double quote", start)
        self.i += 1

    def double_quote_character(self) -> None:
        c = self.script[self.i]
        if c == "$":
            self.variable()
        elif c == "\\" and self.i + 1 < len(self.script) and self.script[self.i + 1] in '"$\\\n':
            if self.script[self.i + 1] != "\n":
                self.literal(self.script[self.i + 1])
            self.i += 2
        else:
            self.literal(c)
            self.i += 1

    def step(self) -> None:
        c, i = self.script[self.i], self.i
        if c in "()*?[]`#" or self.script.startswith("||", i):
            self.fail("unsupported shell syntax", i)
        if c == "!" and (not self.tokens or self.tokens[-1].kind in {TokenKind.NEWLINE, TokenKind.SEMI, TokenKind.PIPE, TokenKind.AND_IF}) and (i + 1 == len(self.script) or self.script[i + 1].isspace()):
            self.fail("unsupported command negation", i)
        if c in " \t\r":
            self.flush(i)
            self.i += 1
        elif c == "\n":
            self.newline()
        elif not self.operator():
            self.word_character(c)

    def newline(self) -> None:
        self.flush(self.i)
        self.tokens.append(Token(TokenKind.NEWLINE, None, self.i, self.i + 1))
        self.i += 1

    def word_character(self, c: str) -> None:
        if self.word_start is None:
            self.word_start = self.i
        if c in "'\"$\\":
            self.word_special(c)
        elif c in "|;&<>":
            self.flush(self.i)
        else:
            self.literal(c)
            self.i += 1

    def word_special(self, c: str) -> None:
        if c in "'\"":
            self.quoted()
        elif c == "$":
            self.variable()
        else:
            self.backslash()

    def backslash(self) -> None:
        i, s = self.i, self.script
        if i + 1 >= len(s):
            self.literal("\\")
            self.i += 1
        elif s[i + 1] == "\n":
            self.i += 2
        elif s[i + 1] in ESCAPABLE or s[i + 1].isspace():
            self.literal(s[i + 1])
            self.i += 2
        else:
            self.literal("\\")
            self.i += 1

    def run(self) -> tuple[Token, ...]:
        while self.i < len(self.script):
            self.step()
        self.flush(len(self.script))
        self.tokens.append(Token(TokenKind.EOF, None, len(self.script), len(self.script)))
        return tuple(self.tokens)
