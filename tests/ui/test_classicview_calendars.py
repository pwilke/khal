"""Tests for ikhal's runtime calendar menu (ClassicView.choose_calendars)."""

from types import SimpleNamespace

import pytest

from khal import calendar_profiles
from khal.ui import ClassicView
from tests.utils import cal0

SIZE = (80, 24)


@pytest.fixture
def conf(tmp_path, monkeypatch):
    monkeypatch.setattr("xdg.BaseDirectory.xdg_data_home", str(tmp_path / "data"))
    (tmp_path / "cache").mkdir()

    def build(collection):
        return {
            "calendars": {name: {"color": "dark blue"} for name in collection.names},
            "highlight_days": {"default_color": ""},
            "ikhal": {"default_profile": None, "profiles": {}},
            "sqlite": {"path": str(tmp_path / "cache" / "khal.db")},
        }

    return build


def _fake_view(collection, conf):
    calls = {"backtrack": 0, "updates": [], "alerts": [], "overlay": None}
    window = SimpleNamespace(
        open=lambda overlay: calls.__setitem__("overlay", overlay),
        backtrack=lambda *a: calls.__setitem__("backtrack", calls["backtrack"] + 1),
        alert=lambda msg: calls["alerts"].append(msg),
    )
    eventscolumn = SimpleNamespace(
        base_widget=SimpleNamespace(
            update=lambda *a, **k: calls["updates"].append((a, k)),
        )
    )
    view = SimpleNamespace(
        collection=collection,
        _conf=conf(collection),
        window=window,
        eventscolumn=eventscolumn,
    )
    return view, calls


def _press(widget, *keys):
    for key in keys:
        widget.keypress(SIZE, key)


def test_choose_calendars_enter_applies_and_remembers(coll_vdirs, conf):
    collection, _ = coll_vdirs
    view, calls = _fake_view(collection, conf)
    names = list(collection.names)

    ClassicView.choose_calendars(view)
    selector = calls["overlay"].top_w
    # the dialog starts with the currently displayed calendars checked
    assert selector._checked() == set(collection.active_names)

    _press(selector, "a")  # uncheck everything
    _press(selector, " ")  # check the focused (first) calendar
    _press(selector, "enter")

    # the active set changes and the display is refreshed
    assert collection.active_names == [cal0]
    assert calls["backtrack"] == 1
    assert calls["updates"] == [((None, None), {"everything": True})]
    assert len(calls["alerts"]) == 1
    # enter remembers the selection for the next start
    assert calendar_profiles.last_selection(view._conf, names) == {cal0}


def test_choose_calendars_peek_does_not_remember(coll_vdirs, conf):
    collection, _ = coll_vdirs
    view, calls = _fake_view(collection, conf)
    names = list(collection.names)

    ClassicView.choose_calendars(view)
    selector = calls["overlay"].top_w
    _press(selector, "a", " ", "p")  # apply once with p

    assert collection.active_names == [cal0]
    assert calls["updates"] == [((None, None), {"everything": True})]
    # p is peek: nothing is remembered, so the next start still shows all
    assert calendar_profiles.last_selection(view._conf, names) == set(names)


def test_choose_calendars_cancel_keeps_display(coll_vdirs, conf):
    collection, _ = coll_vdirs
    before = list(collection.active_names)
    view, calls = _fake_view(collection, conf)

    ClassicView.choose_calendars(view)
    selector = calls["overlay"].top_w
    _press(selector, "a")  # toggle everything off in the dialog
    _press(selector, "esc")  # ... but cancel

    assert collection.active_names == before
    assert calls["backtrack"] == 1
    assert calls["updates"] == []


def test_choose_calendars_needs_more_than_one(coll_vdirs, conf):
    collection, _ = coll_vdirs
    collection._calendars = {cal0: collection._calendars[cal0]}
    view, calls = _fake_view(collection, conf)

    ClassicView.choose_calendars(view)

    assert calls["overlay"] is None
    assert calls["alerts"] == ["Only one calendar configured."]
