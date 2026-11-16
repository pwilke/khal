"""Tests for the persistence behind ikhal's calendar menu and profiles."""

import os

import pytest

from khal import calendar_profiles
from khal.calendar_profiles import (
    Profile,
    last_selection,
    profile_selection,
    save_last_selection,
    save_profile,
)

NAMES = ["home", "work", "birthdays"]
PERSO = Profile("perso", "1", ("home", "birthdays"))


@pytest.fixture
def conf(tmp_path, monkeypatch):
    monkeypatch.setattr("xdg.BaseDirectory.xdg_data_home", str(tmp_path / "data"))
    (tmp_path / "cache").mkdir()
    return {"sqlite": {"path": str(tmp_path / "cache" / "khal.db")}}


def test_last_selection_round_trip(conf):
    # nothing saved yet: everything is shown
    assert last_selection(conf, NAMES) == set(NAMES)
    save_last_selection(conf, {"work"}, NAMES)
    assert last_selection(conf, NAMES) == {"work"}


def test_calendars_configured_later_are_shown(conf):
    save_last_selection(conf, {"work"}, ["home", "work"])
    # birthdays was not configured when the selection was saved, so it is shown
    assert last_selection(conf, NAMES) == {"work", "birthdays"}


def test_saved_profile_overrides_config(conf):
    # the config says perso = home, birthdays; save it with home unchecked
    save_profile(conf, PERSO, {"birthdays"}, NAMES)
    assert profile_selection(conf, PERSO, NAMES) == {"birthdays"}

    # family is added to the profile's config after the selection was saved,
    # so the config decides for it (it is shown), the saved choice decides the rest
    perso2 = Profile("perso", "1", ("home", "birthdays", "family"))
    names = [*NAMES, "family"]
    assert profile_selection(conf, perso2, names) == {"birthdays", "family"}


def test_state_files_are_kept_in_xdg_data_home(conf, tmp_path):
    save_last_selection(conf, {"work"}, NAMES)
    save_profile(conf, PERSO, {"birthdays"}, NAMES)
    assert sorted(p.name for p in (tmp_path / "data" / "khal").iterdir()) == [
        "ikhal_hidden_calendars.json",
        "ikhal_profile_perso.json",
    ]
    assert sorted(p.name for p in (tmp_path / "cache").iterdir()) == []


def test_state_files_next_to_the_database_are_moved(conf, tmp_path):
    (tmp_path / "cache" / "ikhal_profile_perso.json").write_text('{"shown": ["work"]}')
    (tmp_path / "cache" / "ikhal_hidden_calendars.json").write_text('{"hidden": ["home"]}')

    assert last_selection(conf, NAMES) == {"work", "birthdays"}
    assert profile_selection(conf, PERSO, NAMES) == {"home", "work", "birthdays"}
    # reading them moved the files to $XDG_DATA_HOME/khal
    assert list((tmp_path / "cache").iterdir()) == []
    assert (tmp_path / "data" / "khal" / "ikhal_hidden_calendars.json").exists()
    assert (tmp_path / "data" / "khal" / "ikhal_profile_perso.json").exists()


def test_broken_state_file_is_ignored(conf):
    path = calendar_profiles.last_selection_path(conf)

    os.makedirs(os.path.dirname(path))
    with open(path, "w") as f:
        f.write("not json")
    assert last_selection(conf, NAMES) == set(NAMES)


def test_old_state_file_format_is_read(conf):
    path = calendar_profiles.last_selection_path(conf)

    os.makedirs(os.path.dirname(path))
    with open(path, "w") as f:
        f.write('{"hidden": ["home"]}')
    assert last_selection(conf, NAMES) == {"work", "birthdays"}
