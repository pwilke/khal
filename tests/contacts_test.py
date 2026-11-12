import subprocess
import sys

import pytest

from khal.contacts import (
    Contact,
    ContactQueryError,
    build_command,
    parse_query_output,
    query_contacts,
)


def test_build_command_appends_pattern():
    assert build_command("mu cfind --format=mutt-ab", "ali ce") == [
        "mu",
        "cfind",
        "--format=mutt-ab",
        "ali ce",
    ]


def test_build_command_placeholder():
    assert build_command("lookup --query={} --limit 5", "bob") == [
        "lookup",
        "--query=bob",
        "--limit",
        "5",
    ]


def test_parse_query_output():
    output = (
        "Matching addresses in the mu database:\n"
        "alice@example.com\tAlice Liddell\t\n"
        "bob@example.org\t\n"
        "ALICE@example.com\tAlice again\n"
        "not an address\tNobody\n"
        "\n"
    )
    assert parse_query_output(output) == [
        Contact("alice@example.com", "Alice Liddell"),
        Contact("bob@example.org", ""),
    ]


def test_parse_query_output_empty():
    assert parse_query_output("") == []
    assert parse_query_output("No matches\n") == []


def test_contact_str():
    assert str(Contact("a@b.c", "A B")) == "A B <a@b.c>"
    assert str(Contact("a@b.c", "")) == "a@b.c"


def _python_command(script):
    return f"{sys.executable} -c '{script}'"


def test_query_contacts():
    script = 'import sys; print("header"); print(sys.argv[1] + "@example.com\\tSomeone")'
    assert query_contacts(_python_command(script), "carol") == [
        Contact("carol@example.com", "Someone")
    ]


def test_query_contacts_nonzero_exit_is_no_match():
    script = 'import sys; print("no matching contacts", file=sys.stderr); sys.exit(2)'
    assert query_contacts(_python_command(script), "dave") == []


def test_query_contacts_missing_command():
    with pytest.raises(ContactQueryError):
        query_contacts("this-command-does-not-exist-khal", "eve")


def test_query_contacts_timeout(monkeypatch):
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="slow", timeout=1)

    monkeypatch.setattr("khal.contacts.subprocess.run", run)
    with pytest.raises(ContactQueryError):
        query_contacts("slow", "frank")
