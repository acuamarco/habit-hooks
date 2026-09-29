from __future__ import annotations

import re
from dataclasses import dataclass, field

from .command_lexer import lex
from .command_model import AndChain, Assignment, Literal, Pipeline, Redirection, RedirectionKind, Script, SimpleCommand, SourceSpan, Word
from .command_tokens import Token, TokenKind
from .errors import SpecError


_KEYWORDS = {"if", "then", "else", "elif", "fi", "case", "esac", "for", "while", "until", "do", "done", "in", "function", "select", "time", "coproc"}
_BUILTINS = {".", ":", "alias", "bg", "break", "builtin", "caller", "cd", "command", "compgen", "complete", "continue", "declare", "dirs", "disown", "echo", "enable", "eval", "exec", "exit", "export", "false", "fc", "fg", "getopts", "hash", "help", "history", "jobs", "kill", "let", "local", "logout", "mapfile", "popd", "printf", "pushd", "pwd", "read", "readonly", "return", "set", "shift", "shopt", "source", "suspend", "test", "times", "trap", "true", "type", "typeset", "ulimit", "umask", "unalias", "unset", "wait", "[", "]]"}


def parse(script: str, source: SourceSpan = SourceSpan("<inline>", 1)) -> Script:
    return _Parser(script, source, lex(script, source)).run()


class _Parser:
    def __init__(self, script: str, source: SourceSpan, tokens: tuple[Token, ...]):
        self.script, self.source, self.tokens, self.i = script, source, tokens, 0

    def current(self) -> Token:
        return self.tokens[self.i]

    def take(self) -> Token:
        token = self.current()
        self.i += 1
        return token

    def fail(self, message: str, token: Token | None = None) -> None:
        token = token or self.current()
        offset = token.start
        start = self.script.rfind("\n", 0, offset) + 1
        end = self.script.find("\n", offset)
        end = len(self.script) if end < 0 else end
        line, column = self.script[start:end], offset - start + 1
        line_no = self.source.line + self.script[:offset].count("\n")
        raise SpecError(f"{self.source.source}:{line_no}:{column}: {message}\n{line}\n{' ' * (column - 1)}^")

    def skip_newlines(self) -> None:
        while self.current().kind is TokenKind.NEWLINE:
            self.take()

    def run(self) -> Script:
        self.skip_newlines()
        if self.current().kind is TokenKind.EOF:
            self.fail("empty command")
        chains = []
        while self.current().kind is not TokenKind.EOF:
            chains.append(self.and_chain())
            if self.current().kind is TokenKind.EOF:
                break
            self.separator()
        return Script(tuple(chains))

    def separator(self) -> None:
        if self.current().kind not in {TokenKind.SEMI, TokenKind.NEWLINE}:
            self.fail("expected command separator")
        if self.take().kind is TokenKind.SEMI:
            if self.current().kind in {TokenKind.SEMI, TokenKind.EOF}:
                self.fail("empty command")
        self.skip_newlines()

    def and_chain(self) -> AndChain:
        pipelines = [self.pipeline()]
        while self.current().kind is TokenKind.AND_IF:
            self.take()
            self.skip_newlines()
            if self.current().kind in {TokenKind.EOF, TokenKind.SEMI, TokenKind.AND_IF}:
                self.fail("expected command after &&")
            pipelines.append(self.pipeline())
        return AndChain(tuple(pipelines))

    def pipeline(self) -> Pipeline:
        commands = [self.command()]
        while self.current().kind is TokenKind.PIPE:
            self.take()
            self.skip_newlines()
            if self.current().kind in {TokenKind.EOF, TokenKind.SEMI, TokenKind.PIPE, TokenKind.AND_IF}:
                self.fail("expected command after |")
            commands.append(self.command())
        return Pipeline(tuple(commands))

    def command(self) -> SimpleCommand:
        start = self.current().start
        parts = _CommandParts()
        source = SourceSpan(self.source.source, self.source.line + self.script[:start].count("\n"), start - self.script.rfind("\n", 0, start))
        while self.current().kind not in {TokenKind.EOF, TokenKind.SEMI, TokenKind.NEWLINE, TokenKind.PIPE, TokenKind.AND_IF}:
            parts.accept(self, self.take())
        if not parts.command_seen:
            self.fail("assignment-only command or empty command")
        return SimpleCommand(tuple(parts.assignments), tuple(parts.argv), tuple(parts.redirects), source)

    def redirection(self, token: Token) -> Redirection:
        if self.current().kind is not TokenKind.WORD:
            self.fail("redirection requires a target", token)
        target = self.take().value
        descriptor = token.value if isinstance(token.value, int) else 0 if token.kind is TokenKind.REDIR_IN else 1
        kind = {TokenKind.REDIR_IN: RedirectionKind.INPUT, TokenKind.REDIR_OUT: RedirectionKind.OUTPUT, TokenKind.REDIR_APPEND: RedirectionKind.APPEND}[token.kind]
        return Redirection(descriptor, kind, target)

    def literal_word(self, word: Word) -> str:
        if all(isinstance(part, Literal) for part in word.parts):
            return "".join(part.value for part in word.parts)
        return "\0"

    def assignment(self, word: Word) -> Assignment | None:
        if not word.parts or not isinstance(word.parts[0], Literal):
            return None
        first = word.parts[0].value
        match = re.match(r"([A-Za-z_][A-Za-z0-9_]*)=(.*)\Z", first, re.DOTALL)
        if not match:
            return None
        name, value = match.groups()
        parts = ((Literal(value),) if value else ()) + word.parts[1:]
        return Assignment(name, Word(parts or (Literal(""),)))


@dataclass
class _CommandParts:
    assignments: list[Assignment] = field(default_factory=list)
    argv: list[Word] = field(default_factory=list)
    redirects: list[Redirection] = field(default_factory=list)
    command_seen: bool = False

    def accept(self, parser: _Parser, token: Token) -> None:
        if token.kind is TokenKind.WORD:
            self.accept_word(parser, token)
        elif token.kind is TokenKind.FD_DUP:
            self.require_command(parser, token)
            source_fd, target_fd = token.value
            self.redirects.append(Redirection(source_fd, RedirectionKind.DUPLICATE, target_fd))
        elif token.kind in {TokenKind.REDIR_IN, TokenKind.REDIR_OUT, TokenKind.REDIR_APPEND}:
            self.require_command(parser, token)
            self.redirects.append(parser.redirection(token))
        else:
            parser.fail("unexpected token", token)

    def require_command(self, parser: _Parser, token: Token) -> None:
        if not self.command_seen:
            parser.fail("redirections must follow the command name", token)

    def accept_word(self, parser: _Parser, token: Token) -> None:
        word = token.value
        assignment = parser.assignment(word)
        if assignment:
            if self.command_seen:
                parser.fail("command-prefix assignments must precede the command", token)
            self.assignments.append(assignment)
            return
        if not self.command_seen:
            name = parser.literal_word(word)
            if name in _KEYWORDS or name in _BUILTINS:
                parser.fail(f"unsupported command {name!r}", token)
        self.argv.append(word)
        self.command_seen = True
