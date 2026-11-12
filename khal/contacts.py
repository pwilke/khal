# Copyright (c) 2013-2022 khal contributors
#
# Permission is hereby granted, free of charge, to any person obtaining
# a copy of this software and associated documentation files (the
# "Software"), to deal in the Software without restriction, including
# without limitation the rights to use, copy, modify, merge, publish,
# distribute, sublicense, and/or sell copies of the Software, and to
# permit persons to whom the Software is furnished to do so, subject to
# the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE
# LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION
# OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION
# WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.

"""Look up email addresses with an external address book query command.

The command is expected to behave like mutt's ``query_command``: the first
line of its output is a free-form status message, every following line is
``<email>\\t<name>[\\t<other info>]``.  ``mu cfind --format=mutt-ab``,
``khard email --parsable`` and ``abook --mutt-query`` all produce this format.
"""

import logging
import shlex
import subprocess
from typing import NamedTuple

logger = logging.getLogger("khal")

QUERY_TIMEOUT = 10  # seconds


class Contact(NamedTuple):
    email: str
    name: str

    def __str__(self) -> str:
        return f"{self.name} <{self.email}>" if self.name else self.email


class ContactQueryError(Exception):
    pass


def build_command(command: str, pattern: str) -> list[str]:
    """split `command` into arguments and insert `pattern`

    Every ``{}`` in the command is replaced by the pattern, if there is none,
    the pattern is appended as the last argument.
    """
    args = shlex.split(command)
    if any("{}" in arg for arg in args):
        return [arg.replace("{}", pattern) for arg in args]
    return args + [pattern]


def parse_query_output(output: str) -> list[Contact]:
    """parse the output of a mutt-style query command"""
    contacts: list[Contact] = []
    seen: set[str] = set()
    for line in output.splitlines()[1:]:
        fields = line.split("\t")
        email = fields[0].strip()
        if "@" not in email or email.lower() in seen:
            continue
        seen.add(email.lower())
        name = fields[1].strip() if len(fields) > 1 else ""
        contacts.append(Contact(email, name))
    return contacts


def query_contacts(command: str, pattern: str) -> list[Contact]:
    """run the query `command` for `pattern` and return the found contacts

    :raises ContactQueryError: if the command cannot be run
    """
    args = build_command(command, pattern)
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=QUERY_TIMEOUT,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise ContactQueryError(f"Could not run `{args[0]}`: {error}") from error
    # several query commands (e.g. `mu cfind`) exit non-zero if nothing matched
    if result.returncode != 0:
        logger.debug(
            f"contact query `{shlex.join(args)}` exited with {result.returncode}: "
            f"{result.stderr.strip()}"
        )
    return parse_query_output(result.stdout)
