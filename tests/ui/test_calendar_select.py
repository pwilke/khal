import os

import pytest
import urwid

from khal import calendar_profiles
from khal.calendar_profiles import Profile
from khal.ui.calendar_select import CalendarSelector, select_calendars

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


@pytest.fixture
def run_menu(conf, monkeypatch):
    """Run select_calendars, feeding `keys` to the menu instead of a terminal."""

    def run(keys, names=NAMES):
        class FakeLoop:
            def __init__(self, widget, **kw):
                self.widget = widget
                self.screen = type(
                    "Screen", (), {"set_terminal_properties": lambda *a, **k: None}
                )()

            def run(self):
                run.title = _title(self.widget)
                run.initial = self.widget._checked()
                _press(self.widget, *keys[:-1])
                with pytest.raises(urwid.ExitMainLoop):
                    _press(self.widget, keys[-1])

        monkeypatch.setattr("khal.ui.calendar_select.urwid.MainLoop", FakeLoop)
        return select_calendars(conf, names)

    return run


def test_last_selection_is_remembered_on_enter(run_menu):
    assert run_menu([" ", "enter"], names=["home", "work"]) == {"work"}
    assert run_menu(["enter"], names=["home", "work"]) == {"work"}
    # a calendar configured later starts checked
    assert run_menu(["enter"]) == {"work", "birthdays"}


def test_peek_and_quit_do_not_touch_last_selection(run_menu):
    run_menu([" ", "enter"])
    assert run_menu(["a", "p"]) == set(NAMES)
    assert run_menu(["a", "q"]) is None
    assert run_menu(["enter"]) == {"work", "birthdays"}


def test_default_profile_preselects(conf, run_menu):
    conf["ikhal"]["default_profile"] = "pro"
    assert run_menu(["enter"]) == {"work"}
    assert run_menu.title.endswith("[profile: pro]")


def test_saved_profile_overrides_config(conf, run_menu):
    run_menu(["1", " ", "S", "1", "q"])  # perso without home
    assert run_menu(["1", "enter"]) == {"birthdays"}
    conf["calendars"]["family"] = {"color": ""}
    conf["ikhal"]["profiles"]["perso"]["calendars"].append("family")
    # family was not configured when perso was saved, so the config decides
    assert run_menu(["1", "enter"], names=[*NAMES, "family"]) == {"birthdays", "family"}


def test_all_profile(run_menu):
    assert run_menu(["a", "0", "enter"]) == set(NAMES)


def test_state_files_are_kept_in_xdg_data_home(conf, run_menu, tmp_path):
    run_menu([" ", "S", "1", "enter"])
    assert sorted(p.name for p in (tmp_path / "data" / "khal").iterdir()) == [
        "ikhal_hidden_calendars.json",
        "ikhal_profile_perso.json",
    ]
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == []


def test_state_files_next_to_the_database_are_moved(conf, run_menu, tmp_path):
    (tmp_path / "cache" / "ikhal_profile_perso.json").write_text('{"shown": ["work"]}')
    (tmp_path / "cache" / "ikhal_hidden_calendars.json").write_text('{"hidden": ["home"]}')
    run_menu(["enter"])
    assert run_menu.initial == {"work", "birthdays"}
    assert run_menu(["1", "enter"]) == {"home", "work", "birthdays"}
    assert list((tmp_path / "cache").iterdir()) == []
    assert (tmp_path / "data" / "khal" / "ikhal_profile_perso.json").exists()


def test_broken_state_file_is_ignored(conf, run_menu):
    os.makedirs(os.path.dirname(calendar_profiles.last_selection_path(conf)))
    with open(calendar_profiles.last_selection_path(conf), "w") as f:
        f.write("not json")
    assert run_menu(["enter"]) == set(NAMES)


def test_old_state_file_format_is_read(conf, run_menu):
    os.makedirs(os.path.dirname(calendar_profiles.last_selection_path(conf)))
    with open(calendar_profiles.last_selection_path(conf), "w") as f:
        f.write('{"hidden": ["home"]}')
    assert run_menu(["enter"]) == {"work", "birthdays"}


def test_never_starts_with_nothing_checked(conf, run_menu):
    run_menu(["a", "a", " ", "S", "1", "q"])  # perso = home only
    assert run_menu(["enter"], names=["work", "birthdays"])
    assert run_menu.initial == {"work", "birthdays"}


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
