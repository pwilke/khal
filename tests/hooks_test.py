import logging
import shlex
import threading

from khal.khalendar import CalendarCollection
from khal.khalendar.hooks import PostWriteHook

from .utils import LOCALE_BERLIN, _get_text, cal1, cal2


def _counter(tmpdir):
    """a shell command logging each run's environment, and a function reading that log"""
    path = tmpdir.join("runs")
    command = f'echo "$KHAL_CALENDAR $KHAL_CALENDAR_PATH" >> {shlex.quote(str(path))}'

    def runs():
        return path.read().splitlines() if path.exists() else []

    return command, runs


def test_no_command_is_a_noop():
    hook = PostWriteHook(None)
    hook.notify("one", "/cal/one")
    hook.start_background()
    hook.close()
    assert hook._thread is None
    assert hook._pending == {}


def test_empty_command_is_disabled():
    assert PostWriteHook("").command is None


def test_foreground_runs_once_per_calendar_on_close(tmpdir):
    command, runs = _counter(tmpdir)
    hook = PostWriteHook(command)
    hook.notify("one", "/cal/one/")
    hook.notify("two", "/cal/pair/two")
    hook.notify("one", "/cal/one/")
    assert runs() == []
    hook.close()
    assert runs() == ["one /cal/one", "two /cal/pair/two"]


def test_foreground_without_writes_does_not_run(tmpdir):
    command, runs = _counter(tmpdir)
    hook = PostWriteHook(command)
    hook.close()
    assert runs() == []


def test_path_is_normalized():
    hook = PostWriteHook("true")
    hook.notify("one", "/cal//pair/./one/")
    assert hook._pending == {"one": "/cal/pair/one"}


def test_background_runs_after_write(tmpdir):
    command, runs = _counter(tmpdir)
    hook = PostWriteHook(command)
    hook.start_background()
    hook.notify("one", "/cal/one")
    hook.close()
    assert runs() == ["one /cal/one"]
    assert hook._thread is None


def test_background_coalesces_writes_during_run(tmpdir):
    """writes made while the command runs lead to exactly one more run per calendar"""
    command, runs = _counter(tmpdir)
    hook = PostWriteHook(command)
    started = threading.Event()
    release = threading.Event()
    real_run = hook._run

    def slow_run(calendar, path, quiet):
        started.set()
        release.wait(5)
        real_run(calendar, path, quiet)

    hook._run = slow_run
    hook.start_background()
    hook.notify("one", "/cal/one")
    assert started.wait(5)
    hook.notify("one", "/cal/one")
    hook.notify("two", "/cal/two")
    hook.notify("one", "/cal/one")
    release.set()
    hook.close()
    assert runs() == ["one /cal/one", "one /cal/one", "two /cal/two"]


def test_background_output_is_reported():
    hook = PostWriteHook('echo "synced $KHAL_CALENDAR"; echo oops >&2')
    reports = []
    hook.on_output = reports.append
    hook.start_background()
    hook.notify("one", "/cal/one")
    hook.close()
    assert len(reports) == 1
    header, *lines = reports[0].splitlines()
    assert header.endswith("post_write_command for one exited with status 0:")
    assert lines == ["  synced one", "  oops"]


def test_background_failure_is_reported_and_logged(caplog):
    hook = PostWriteHook("echo nope; exit 2")
    reports = []
    hook.on_output = reports.append
    hook.start_background()
    hook.notify("one", "/cal/one")
    with caplog.at_level(logging.ERROR, logger="khal"):
        hook.close()
    assert "exited with status 2:" in reports[0]
    assert reports[0].endswith("  nope")
    assert "post_write_command for one exited with status 2" in caplog.text


def test_background_long_output_is_truncated():
    hook = PostWriteHook("seq 1 80")
    reports = []
    hook.on_output = reports.append
    hook.start_background()
    hook.notify("one", "/cal/one")
    hook.close()
    lines = reports[0].splitlines()
    assert lines[1] == "  [... 30 lines skipped]"
    assert lines[2] == "  31"
    assert lines[-1] == "  80"


def test_background_without_output_says_so():
    hook = PostWriteHook("true")
    reports = []
    hook.on_output = reports.append
    hook.start_background()
    hook.notify("one", "/cal/one")
    hook.close()
    assert reports[0].endswith("exited with status 0, no output")


def test_failing_command_is_logged(caplog):
    hook = PostWriteHook("exit 3")
    hook.notify("one", "/cal/one")
    with caplog.at_level(logging.ERROR, logger="khal"):
        hook.close()
    assert "post_write_command for one exited with status 3" in caplog.text


def _collection(tmpdir, command):
    calendars = {}
    for name in (cal1, cal2):
        calendars[name] = {
            "name": name,
            "path": str(tmpdir.mkdir(name)) + "/",
            "readonly": False,
            "color": "",
            "priority": 10,
            "ctype": "calendar",
            "addresses": "",
        }
    return CalendarCollection(
        calendars=calendars,
        dbpath=":memory:",
        locale=LOCALE_BERLIN,
        post_write_command=command,
    )


def test_collection_writes_notify_the_written_calendar(tmpdir):
    coll = _collection(tmpdir, "true")
    notified = []
    coll.post_write_hook.notify = lambda calendar, path: notified.append((calendar, path))
    path1 = str(tmpdir.join(cal1)) + "/"
    path2 = str(tmpdir.join(cal2)) + "/"

    event = coll.create_event_from_ics(_get_text("event_dt_simple"), cal1)
    coll.insert(event)
    assert notified == [(cal1, path1)]

    event = coll.get_event(event.href, cal1)
    coll.update(event)
    coll.force_update(event)
    assert notified[1:] == [(cal1, path1), (cal1, path1)]

    del notified[:]
    event = coll.get_event(event.href, cal1)
    coll.change_collection(event, cal2)
    assert notified == [(cal2, path2), (cal1, path1)]  # insert, then delete

    del notified[:]
    event = coll.get_event(event.href, cal2)
    coll.delete(event.href, event.etag, cal2)
    assert notified == [(cal2, path2)]


def test_collection_runs_command_per_changed_calendar(tmpdir):
    command, runs = _counter(tmpdir)
    coll = _collection(tmpdir, command)
    event = coll.create_event_from_ics(_get_text("event_dt_simple"), cal1)
    coll.insert(event)
    event = coll.get_event(event.href, cal1)
    coll.change_collection(event, cal2)
    assert runs() == []
    coll.post_write_hook.close()
    assert sorted(runs()) == sorted([f"{cal1} {tmpdir.join(cal1)}", f"{cal2} {tmpdir.join(cal2)}"])


def test_build_collection_registers_close(tmpdir, monkeypatch):
    from khal import cli_utils

    registered = []
    monkeypatch.setattr(cli_utils.atexit, "register", registered.append)

    conf = {
        "calendars": {
            cal1: {
                "path": str(tmpdir.mkdir(cal1)),
                "readonly": False,
                "color": "",
                "priority": 10,
                "type": "calendar",
            }
        },
        "highlight_days": {
            "color": "",
            "method": "fg",
            "default_color": "",
            "multiple": "",
            "multiple_on_overflow": False,
        },
        "locale": LOCALE_BERLIN,
        "sqlite": {"path": ":memory:"},
        "default": {
            "highlight_event_days": False,
            "default_calendar": None,
            "post_write_command": None,
        },
    }
    cli_utils.build_collection(conf, None)
    assert registered == []

    conf["default"]["post_write_command"] = "true"
    collection = cli_utils.build_collection(conf, None)
    assert registered == [collection.post_write_hook.close]
