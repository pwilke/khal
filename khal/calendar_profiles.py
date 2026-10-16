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

"""Which calendars ikhal shows: the last selection and named profiles.

Profiles are declared in the `[ikhal]` section of the config file. Saving a
profile from ikhal's startup menu writes its selection to a file in
$XDG_DATA_HOME/khal, which then takes precedence over the calendars listed in
the config.
Saved files record both the shown and the hidden calendars, so that calendars
configured later fall back to what the config file says for that profile.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass

import xdg.BaseDirectory

logger = logging.getLogger("khal")

ALL_CALENDARS = "*"

# keys used by the startup menu itself, they cannot select a profile
RESERVED_KEYS = frozenset(
    [" ", "enter", "esc", "a", "p", "q", "S", "up", "down", "page up", "page down", "home", "end"]
)


@dataclass(frozen=True)
class Profile:
    name: str
    key: str | None
    calendars: tuple[str, ...]


def get_profiles(conf) -> dict[str, Profile]:
    """Return the profiles declared in the config, warning about unusable hotkeys."""
    profiles = {}
    used_keys: dict[str, str] = {}
    for name, section in conf["ikhal"]["profiles"].items():
        key = section["key"]
        if key in RESERVED_KEYS:
            logger.warning(f"ikhal profile {name}: key {key!r} is used by the menu, ignoring it")
            key = None
        elif key in used_keys:
            logger.warning(
                f"ikhal profile {name}: key {key!r} is already used by profile "
                f"{used_keys[key]}, ignoring it"
            )
            key = None
        elif key is not None:
            used_keys[key] = name
        unknown = [
            cal
            for cal in section["calendars"]
            if cal not in conf["calendars"] and cal != ALL_CALENDARS
        ]
        if unknown:
            logger.warning(f"ikhal profile {name}: unknown calendars {', '.join(unknown)}")
        profiles[name] = Profile(name, key, tuple(section["calendars"]))
    return profiles


def _state_path(conf, filename: str) -> str:
    """Path of a state file, which should survive clearing the cache, unlike the database."""
    path = os.path.join(xdg.BaseDirectory.xdg_data_home, "khal", filename)
    # these files used to live next to the database, by default in $XDG_CACHE_HOME
    legacy = os.path.join(os.path.dirname(conf["sqlite"]["path"]), filename)
    if legacy != path and not os.path.exists(path) and os.path.exists(legacy):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            os.replace(legacy, path)
            logger.info(f"Moved {legacy} to {path}")
        except OSError as error:
            logger.warning(f"Could not move {legacy} to {path}: {error}")
            return legacy
    return path


def profile_path(conf, name: str) -> str:
    safe_name = re.sub(r"[^\w.-]", "_", name)
    return _state_path(conf, f"ikhal_profile_{safe_name}.json")


def last_selection_path(conf) -> str:
    return _state_path(conf, "ikhal_hidden_calendars.json")


def _load(path: str) -> dict[str, set[str]] | None:
    try:
        with open(path) as f:
            data = json.load(f)
        return {
            field: {name for name in data.get(field, []) if isinstance(name, str)}
            for field in ("shown", "hidden")
        }
    except FileNotFoundError:
        return None
    except (OSError, ValueError, AttributeError, TypeError) as error:
        logger.warning(f"Ignoring unreadable calendar selection in {path}: {error}")
        return None


def _save(path: str, selection: set[str], names: list[str]) -> None:
    """Save `selection` out of `names`, keeping what was saved for unconfigured calendars."""
    old = _load(path) or {"shown": set(), "hidden": set()}
    data = {
        "shown": sorted((old["shown"] - set(names)) | selection),
        "hidden": sorted((old["hidden"] - set(names)) | (set(names) - selection)),
    }
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
    except OSError as error:
        logger.warning(f"Could not save calendar selection to {path}: {error}")


def _resolve(saved: dict[str, set[str]] | None, default: set[str], names: list[str]) -> set[str]:
    if saved is None:
        return set(default)
    return {
        name
        for name in names
        if name in saved["shown"] or (name in default and name not in saved["hidden"])
    }


def profile_selection(conf, profile: Profile, names: list[str]) -> set[str]:
    """The calendars among `names` that `profile` shows."""
    if ALL_CALENDARS in profile.calendars:
        default = set(names)
    else:
        default = set(profile.calendars) & set(names)
    return _resolve(_load(profile_path(conf, profile.name)), default, names)


def save_profile(conf, profile: Profile, selection: set[str], names: list[str]) -> None:
    _save(profile_path(conf, profile.name), selection, names)


def last_selection(conf, names: list[str]) -> set[str]:
    """The calendars chosen last time, calendars configured since then are shown."""
    return _resolve(_load(last_selection_path(conf)), set(names), names)


def save_last_selection(conf, selection: set[str], names: list[str]) -> None:
    _save(last_selection_path(conf), selection, names)
