from __future__ import annotations

import pytest

from tests.harness.command_lexer import TokenKind, lex
from tests.harness.command_model import Literal, SourceSpan, Variable
from tests.harness.command_model import RedirectionKind
from tests.harness.command_parser import parse
from tests.harness.errors import SpecError


def words(script: str):
    return [token.value.parts for token in lex(script) if token.kind is TokenKind.WORD]


def test_lexer_joins_adjacent_parts_and_preserves_empty_words():
    assert words("ab' c'\"$NAME\" ''") == [
        (Literal("ab c"), Variable("NAME")),
        (Literal(""),),
    ]


def test_lexer_keeps_single_quoted_jq_literal_and_windows_backslashes():
    assert words("jq '.x | select(.name == \"$name\")' C:\\Users\\me\\file") == [
        (Literal("jq"),),
        (Literal(".x | select(.name == \"$name\")"),),
        (Literal("C:\\Users\\me\\file"),),
    ]


def test_lexer_expands_braced_and_unbraced_variables():
    assert words("$NAME/${PWD}/$PATHSEP/$PYTHON") == [
        (Variable("NAME"), Literal("/"), Variable("PWD"), Literal("/"), Variable("PATHSEP"), Literal("/"), Variable("PYTHON")),
    ]


def test_lexer_keeps_multiline_double_quoted_words_together():
    assert words('"first\nsecond" next') == [
        (Literal("first\nsecond"),),
        (Literal("next"),),
    ]


def test_lexer_emits_ordered_operators_and_complete_fd_dup_tokens():
    tokens = lex("2>&1 1>&2 >&2 2>>file | cmd && next; done\n")
    assert [token.kind for token in tokens] == [
        TokenKind.FD_DUP, TokenKind.FD_DUP, TokenKind.FD_DUP,
        TokenKind.REDIR_APPEND, TokenKind.WORD, TokenKind.PIPE,
        TokenKind.WORD, TokenKind.AND_IF, TokenKind.WORD,
        TokenKind.SEMI, TokenKind.WORD, TokenKind.NEWLINE, TokenKind.EOF,
    ]
    assert [tokens[i].value for i in range(3)] == [(2, 1), (1, 2), (1, 2)]


@pytest.mark.parametrize("script", ["2> &1", "2>& 1", "0>&1", "3>&1", "||", "&", "! echo forbidden", "$(id)", "<(id)", "`id`", "*.py", "foo # comment", "${bad-name}"])
def test_lexer_rejects_unsupported_syntax(script: str):
    with pytest.raises(SpecError):
        lex(script)


def test_lexer_reports_source_offsets_for_unterminated_quote():
    with pytest.raises(SpecError, match=r"sample.spec:8:3"):
        lex("a 'broken", source=SourceSpan("sample.spec", 8))


def test_parser_applies_pipeline_and_sequence_precedence():
    parsed = parse("a | b && c ; d")
    assert len(parsed.chains) == 2
    assert len(parsed.chains[0].pipelines) == 2
    assert len(parsed.chains[0].pipelines[0].commands) == 2
    assert parsed.chains[1].pipelines[0].commands[0].argv[0].parts == (Literal("d"),)


def test_parser_preserves_assignment_expansion_and_redirection_order():
    command = parse("A=$VALUE tool 2>&1 >out").chains[0].pipelines[0].commands[0]
    assert command.assignments[0].name == "A"
    assert command.assignments[0].value.parts == (Variable("VALUE"),)
    assert [item.kind for item in command.redirections] == [RedirectionKind.DUPLICATE, RedirectionKind.OUTPUT]


@pytest.mark.parametrize("script", [
    "", ";a", "a;;b", "a |", "a &&", "A=1", "tool A=1", ">out tool", "2>&1 tool",
    "cat <<EOF", "cat <<<text", "echo $(id)", "echo <(id)", "echo `id`",
    "echo *.py", "echo (group)", "echo x # comment", "! echo x",
    "if true", "for x in a; do echo x; done", "name() { echo x; }",
    "export X=1", "echo x || other", "echo x &",
])
def test_parser_rejects_empty_or_unsupported_commands(script: str):
    with pytest.raises(SpecError):
        parse(script)
