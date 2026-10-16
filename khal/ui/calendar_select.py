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

"""A small startup menu that lets the user pick which calendars ikhal shows."""

from __future__ import annotations

from collections.abc import Callable, Iterable

import urwid

from khal import calendar_profiles
from khal.calendar_profiles import Profile

from . import _urwid_palette_entry

HELP = (
    "space: toggle  a: all/none  enter: open and remember  p: peek (open, don't remember)  q: quit"
)


class CalendarCheckBox(urwid.CheckBox):
    """A CheckBox that only toggles on space, leaving enter to confirm."""

    def keypress(self, size, key):
        if key == "enter":
            return key
        return super().keypress(size, key)


class CalendarSelector(urwid.WidgetWrap):
    def __init__(
        self,
        conf,
        names: list[str],
        checked: Iterable[str],
        profiles: Iterable[Profile] = (),
        load_profile: Callable[[Profile], set[str]] = lambda profile: set(),
        save_profile: Callable[[Profile, set[str]], None] = lambda profile, selection: None,
        profile: Profile | None = None,
    ):
        self.selection: set[str] | None = None
        self.remember = False
        self._load_profile = load_profile
        self._save_profile = save_profile
        self._profiles = {p.key: p for p in profiles if p.key is not None}
        self._profile = profile
        self._modified = False
        self._choosing_profile_to_save = False
        self._loading = False

        checked = set(checked)
        self._boxes = {
            name: CalendarCheckBox(
                self._label(conf, name), state=name in checked, on_state_change=self._toggled
            )
            for name in names
        }
        self._title = urwid.Text("")
        self._status = urwid.Text(HELP)
        footer = [self._status]
        if self._profiles:
            keys = "  ".join(f"{key}: {p.name}" for key, p in self._profiles.items())
            footer.append(urwid.Text(f"profiles  {keys}  S: save to profile"))
        body = urwid.ListBox(urwid.SimpleFocusListWalker(list(self._boxes.values())))
        frame = urwid.Frame(
            body,
            header=urwid.AttrMap(self._title, "header"),
            footer=urwid.AttrMap(urwid.Pile(footer), "footer"),
        )
        self._update_title()
        super().__init__(urwid.LineBox(frame))

    @staticmethod
    def _label(conf, name):
        color = conf["calendars"][name]["color"] or conf["highlight_days"]["default_color"]
        if not color:
            return f"  {name}"
        return [(f"calendar {name}", "■ "), name]

    def _toggled(self, box, state):
        if not self._loading and not self._modified:
            self._modified = True
            self._update_title()

    def _update_title(self):
        title = "Select calendars to display"
        if self._profile is not None:
            title += f"  [profile: {self._profile.name}{' (modified)' if self._modified else ''}]"
        self._title.set_text(title)

    def _checked(self) -> set[str]:
        return {name for name, box in self._boxes.items() if box.get_state()}

    def _set_checked(self, checked: set[str]):
        self._loading = True
        try:
            for name, box in self._boxes.items():
                box.set_state(name in checked)
        finally:
            self._loading = False

    def _save_to(self, key):
        self._choosing_profile_to_save = False
        profile = self._profiles.get(key)
        selection = self._checked()
        if profile is None:
            self._status.set_text("Not saved. " + HELP)
        elif not selection:
            self._status.set_text("Not saved, select at least one calendar. " + HELP)
        else:
            self._save_profile(profile, selection)
            self._profile, self._modified = profile, False
            self._update_title()
            self._status.set_text(f"Saved to profile {profile.name}. " + HELP)

    def keypress(self, size, key):
        if self._choosing_profile_to_save:
            self._save_to(key)
            return None
        key = super().keypress(size, key)
        if key == "a":
            self._set_checked(set() if self._checked() == set(self._boxes) else set(self._boxes))
            self._toggled(None, None)
        elif key in ("enter", "p"):
            selection = self._checked()
            if not selection:
                self._status.set_text("Select at least one calendar. " + HELP)
            else:
                self.selection = selection
                self.remember = key == "enter"
                raise urwid.ExitMainLoop()
        elif key in ("q", "esc"):
            raise urwid.ExitMainLoop()
        elif key == "S" and self._profiles:
            self._choosing_profile_to_save = True
            keys = "  ".join(f"{key}: {p.name}" for key, p in self._profiles.items())
            self._status.set_text(f"Save to which profile? {keys}  (any other key: cancel)")
        elif key in self._profiles:
            profile = self._profiles[key]
            self._set_checked(self._load_profile(profile))
            self._profile, self._modified = profile, False
            self._update_title()
            self._status.set_text(f"Loaded profile {profile.name}. " + HELP)
        else:
            return key
        return None


def _palette(conf, names):
    palette = [("header", "bold", ""), ("footer", "light gray", "")]
    for name in names:
        color = conf["calendars"][name]["color"] or conf["highlight_days"]["default_color"]
        # strip alpha values, urwid does not understand them
        if color and color[0] == "#" and len(color) in (5, 9):
            color = color[: len(color) - (1 if len(color) == 5 else 2)]
        if color:
            palette.append(_urwid_palette_entry(f"calendar {name}", color, "fg", "rgb"))
    return palette


def select_calendars(conf, names: list[str]) -> set[str] | None:
    """Let the user choose among `names`.

    The menu starts with the default profile if one is configured, and with
    the calendars chosen last time otherwise.

    :returns: the chosen calendar names, or None if the user quit
    """
    profiles = calendar_profiles.get_profiles(conf)
    profile = profiles.get(conf["ikhal"]["default_profile"])
    if profile is not None:
        checked = calendar_profiles.profile_selection(conf, profile, names)
    else:
        checked = calendar_profiles.last_selection(conf, names)
    if not checked:  # never start with everything unchecked
        checked, profile = set(names), None

    selector = CalendarSelector(
        conf,
        names,
        checked,
        profiles=profiles.values(),
        load_profile=lambda p: calendar_profiles.profile_selection(conf, p, names),
        save_profile=lambda p, selection: calendar_profiles.save_profile(conf, p, selection, names),
        profile=profile,
    )
    loop = urwid.MainLoop(
        selector,
        palette=_palette(conf, names),
        handle_mouse=conf["default"]["enable_mouse"],
    )
    loop.screen.set_terminal_properties(colors=2**24)
    loop.run()
    if selector.selection is not None and selector.remember:
        calendar_profiles.save_last_selection(conf, selector.selection, names)
    return selector.selection
