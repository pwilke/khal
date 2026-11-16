import pytest
import urwid

from khal import calendar_profiles
from khal.calendar_profiles import Profile
from khal.ui.calendar_select import CalendarSelector

NAMES = ["home", "work", "birthdays"]
SIZE = (80, 24)
PERSO = Profile("perso", "1", ("home", "birthdays"))
PRO = Profile("pro", "2", ("work",))


@pytest.fixture
def conf(tmp_path, monkeypatch):
    monkeypatch.setattr("xdg.BaseDirectory.xdg_data_home", str(tmp_path / "data"))
    (tmp_path / "cache").mkdir()
    return {
        "calendars": {
            "home": {"color": "dark red"},
            "work": {"color": "#00ff00ff"},
            "birthdays": {"color": ""},
        },
        "highlight_days": {"default_color": ""},
        "sqlite": {"path": str(tmp_path / "cache" / "khal.db")},
        "default": {"enable_mouse": False},
        "ikhal": {
            "default_profile": None,
            "profiles": {
                "perso": {"key": "1", "calendars": ["home", "birthdays"]},
                "pro": {"key": "2", "calendars": ["work"]},
                "all": {"key": "0", "calendars": ["*"]},
            },
        },
    }


def _press(widget, *keys):
    for key in keys:
        widget.keypress(SIZE, key)


def _confirm(widget, key="enter"):
    with pytest.raises(urwid.ExitMainLoop):
        _press(widget, key)
    return widget.selection


def _selector(conf, checked=NAMES, **kwargs):
    return CalendarSelector(conf, NAMES, checked, **kwargs)


def _title(selector):
    return selector._title.get_text()[0]


def test_enter_confirms_and_remembers(conf):
    selector = _selector(conf)
    assert _confirm(selector) == set(NAMES)
    assert selector.remember


def test_peek_confirms_without_remembering(conf):
    selector = _selector(conf)
    _press(selector, " ")
    assert _confirm(selector, "p") == {"work", "birthdays"}
    assert not selector.remember


def test_space_toggles_focused_calendar(conf):
    selector = _selector(conf, checked={"home"})
    _press(selector, " ", "down", " ")
    assert _confirm(selector) == {"work"}


def test_toggle_all_and_refuse_empty_selection(conf):
    selector = _selector(conf)
    _press(selector, "a", "enter")  # nothing selected: stays open
    assert selector.selection is None
    _press(selector, "a")
    assert _confirm(selector) == set(NAMES)


def test_quit_returns_no_selection(conf):
    selector = _selector(conf)
    with pytest.raises(urwid.ExitMainLoop):
        _press(selector, "q")
    assert selector.selection is None


def test_profile_hotkey_loads_profile(conf):
    loaded = {"perso": {"home", "birthdays"}, "pro": {"work"}}
    selector = _selector(conf, profiles=[PERSO, PRO], load_profile=lambda p: loaded[p.name])
    _press(selector, "2")
    assert "profile: pro" in _title(selector)
    _press(selector, " ")
    assert "(modified)" in _title(selector)
    _press(selector, "1")
    assert _title(selector).endswith("[profile: perso]")
    assert _confirm(selector) == {"home", "birthdays"}


def test_save_to_profile(conf):
    saved = []
    selector = _selector(
        conf, profiles=[PERSO, PRO], save_profile=lambda p, sel: saved.append((p.name, sel))
    )
    _press(selector, " ", "S", "2")
    assert saved == [("pro", {"work", "birthdays"})]
    assert _title(selector).endswith("[profile: pro]")
    _press(selector, "S", "x")  # any other key cancels
    _press(selector, "a", "a", "S", "1")  # nothing checked: not saved
    assert saved == [("pro", {"work", "birthdays"})]


def test_save_key_does_nothing_without_profiles(conf):
    selector = _selector(conf)
    _press(selector, "S", "1")
    assert _confirm(selector) == set(NAMES)


def test_callbacks_replace_exit_main_loop(conf):
    """With on_select/on_cancel the widget drives an embedded dialog instead
    of raising ExitMainLoop (used by the runtime calendar menu)."""
    selected, cancelled = [], []
    selector = _selector(
        conf,
        checked={"home"},
        on_select=lambda sel, remember: selected.append((sel, remember)),
        on_cancel=lambda: cancelled.append(True),
    )
    # empty selection does not fire on_select
    _press(selector, " ", "enter")
    assert selected == []
    _press(selector, "down", " ")  # check "work"
    _press(selector, "enter")
    assert selected == [({"work"}, True)]
    _press(selector, "p")
    assert selected[-1] == ({"work"}, False)
    _press(selector, "esc")
    assert cancelled == [True]
    _press(selector, "q")
    assert cancelled == [True, True]


def test_unusable_profile_keys_are_dropped(conf, caplog):
    conf["ikhal"]["profiles"]["bad"] = {"key": "q", "calendars": []}
    conf["ikhal"]["profiles"]["dup"] = {"key": "1", "calendars": ["nope"]}
    profiles = calendar_profiles.get_profiles(conf)
    assert profiles["bad"].key is None
    assert profiles["dup"].key is None
    assert profiles["perso"].key == "1"
    assert "used by the menu" in caplog.text
    assert "already used by profile perso" in caplog.text
    assert "unknown calendars nope" in caplog.text
