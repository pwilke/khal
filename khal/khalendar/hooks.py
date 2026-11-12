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
#
"""Run a user-configured shell command after khal wrote to a vdir."""

import logging
import os
import subprocess
import threading
import time
from collections.abc import Callable

logger = logging.getLogger("khal")

# at most this many lines of a background run's output are passed to on_output
MAX_OUTPUT_LINES = 50


class PostWriteHook:
    """Runs ``command`` once for each calendar khal wrote to.

    The command runs through the shell with two environment variables set:
    ``KHAL_CALENDAR`` (the calendar's name in khal's config) and
    ``KHAL_CALENDAR_PATH`` (the calendar's vdir, normalized, without a
    trailing slash).

    By default (foreground mode, used by the CLI) writes are only recorded and
    the command runs when :meth:`close` is called, once per changed calendar.
    This way a ``khal import`` of many events into one calendar triggers a
    single run.

    In background mode (used by ikhal, see :meth:`start_background`) the command
    runs in a worker thread after each write. Its output is captured so it
    doesn't garble the TUI, and handed to :attr:`on_output` (ikhal shows it in
    its log pane) as a single report per run. Writes that happen while the
    command is running are coalesced into one more run per calendar, and two
    runs never overlap.
    """

    def __init__(self, command: str | None = None) -> None:
        self.command = command or None
        self._pending: dict[str, str] = {}
        self._lock = threading.Lock()
        self._wakeup = threading.Event()
        self._stop = False
        self._thread: threading.Thread | None = None
        # receives a report (a header line, then the output) after each
        # background run; called from the worker thread
        self.on_output: Callable[[str], None] | None = None

    def notify(self, calendar: str, path: str) -> None:
        """Record that `calendar`, stored at `path`, was written to."""
        if self.command is None:
            return
        with self._lock:
            self._pending[calendar] = os.path.normpath(path)
        self._wakeup.set()

    def start_background(self) -> None:
        """Run the command in a worker thread after each write from now on."""
        if self.command is None or self._thread is not None:
            return
        self._thread = threading.Thread(target=self._worker, name="khal-post-write", daemon=True)
        self._thread.start()

    def close(self) -> None:
        """Run any outstanding commands and wait for them to finish."""
        if self.command is None:
            return
        if self._thread is not None:
            self._stop = True
            self._wakeup.set()
            self._thread.join()
            self._thread = None
        else:
            self._run_pending(quiet=False)

    def _take_pending(self) -> dict[str, str]:
        with self._lock:
            pending, self._pending = self._pending, {}
        return pending

    def _worker(self) -> None:
        while True:
            self._wakeup.wait()
            self._wakeup.clear()
            self._run_pending(quiet=True)
            if self._stop and not self._pending:
                return

    def _run_pending(self, quiet: bool) -> None:
        for calendar, path in self._take_pending().items():
            self._run(calendar, path, quiet)

    def _run(self, calendar: str, path: str, quiet: bool) -> None:
        assert self.command is not None
        logger.debug(f"running post_write_command for {calendar}: {self.command}")
        env = {**os.environ, "KHAL_CALENDAR": calendar, "KHAL_CALENDAR_PATH": path}
        try:
            if quiet:
                result = subprocess.run(
                    self.command,
                    shell=True,
                    env=env,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    errors="replace",
                    check=False,
                )
                self._report(calendar, result.returncode, result.stdout)
            else:
                result = subprocess.run(
                    self.command, shell=True, env=env, stdin=subprocess.DEVNULL, check=False
                )
        except OSError as error:
            logger.error(f"post_write_command for {calendar} failed: {error}")
            return
        if result.returncode != 0:
            logger.error(
                f"post_write_command for {calendar} exited with status {result.returncode}"
            )

    def _report(self, calendar: str, returncode: int, output: str) -> None:
        if self.on_output is None:
            return
        lines = output.rstrip().splitlines()
        if len(lines) > MAX_OUTPUT_LINES:
            skipped = len(lines) - MAX_OUTPUT_LINES
            lines = [f"[... {skipped} lines skipped]", *lines[-MAX_OUTPUT_LINES:]]
        header = (
            f"{time.strftime('%H:%M:%S')} post_write_command for {calendar} "
            f"exited with status {returncode}" + (":" if lines else ", no output")
        )
        try:
            self.on_output("\n".join([header, *("  " + line for line in lines)]))
        except Exception as error:  # never let a display problem kill the worker
            logger.debug(f"could not report post_write_command output: {error}")
