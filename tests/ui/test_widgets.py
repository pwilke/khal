import pytest
import urwid

from khal.contacts import Contact
from khal.ui.widgets import (
    AttendeeEdit,
    CompletionList,
    FocusLineBoxColor,
    FocusLineBoxTop,
    FocusLineBoxWidth,
    current_address_span,
    delete_last_word,
)


def test_delete_last_word():
    tests = [
        ("Fü1ü  Bär!", "Fü1ü  Bär", 1),
        ("Füü Bär1", "Füü ", 1),
        ("Füü1 Bär1", "Füü1 ", 1),
        (" Füü Bär", " Füü ", 1),
        ("Füü Bär.Füü", "Füü Bär.", 1),
        ("Füü Bär.(Füü)", "Füü Bär.(Füü", 1),
        ("Füü ", "", 1),
        ("Füü  ", "", 1),
        ("Füü", "", 1),
        ("", "", 1),
        ("Füü Bär.(Füü)", "Füü Bär.", 3),
        ("Füü Bär1", "", 2),
        (
            "Lorem ipsum dolor sit amet, consetetur sadipscing elitr, "
            "sed diam nonumy eirmod tempor invidunt ut labore et dolore "
            "magna aliquyam erat, sed diam volest.",
            "Lorem ipsum dolor sit amet, consetetur sadipscing elitr, "
            "sed diam nonumy eirmod tempor invidunt ut labore ",
            10,
        ),
    ]

    for org, short, number in tests:
        assert delete_last_word(org, number) == short


@pytest.mark.parametrize("cls", [FocusLineBoxColor, FocusLineBoxTop, FocusLineBoxWidth])
def test_focus_line_box(cls):
    inner = urwid.Filler(urwid.Text("test"))
    box = cls(inner)
    assert box.original_widget is inner
    box.render((20, 10), focus=False)
    box.render((20, 10), focus=True)


@pytest.mark.parametrize(
    ("text", "pos", "expected"),
    [
        ("", 0, ""),
        ("ali", 3, "ali"),
        ("ali", 1, "ali"),
        ("a@b.c, bo", 9, "bo"),
        ("a@b.c,  bo  , c@d.e", 9, "bo"),
        ("a@b.c, bo, c@d.e", 2, "a@b.c"),
        ("a@b.c, ", 7, ""),
    ],
)
def test_current_address_span(text, pos, expected):
    start, end = current_address_span(text, pos)
    assert text[start:end] == expected


CONTACTS = {
    "ali": [Contact("alice@example.com", "Alice")],
    "alice@example.com": [Contact("alice@example.com", "Alice")],
    "bo": [Contact("bob@example.com", "Bob"), Contact("bo@example.org", "Bo")],
}


class Recorder:
    def __init__(self):
        self.queries = []
        self.errors = []

    def query(self, pattern):
        self.queries.append(pattern)
        return CONTACTS.get(pattern, [])

    def on_error(self, msg):
        self.errors.append(msg)


def make_edit(text, recorder, query=True):
    edit = AttendeeEdit(
        query=recorder.query if query else None,
        on_error=recorder.on_error,
        caption="Attendees: ",
        edit_text=text,
        multiline=True,
    )
    edit._edit.set_edit_pos(len(text))
    return edit


def test_attendee_edit_single_match():
    rec = Recorder()
    edit = make_edit("x@y.z, ali", rec)
    assert edit.keypress((60,), "tab") is None
    assert edit.get_edit_text() == "x@y.z, alice@example.com"
    assert edit._edit.edit_pos == len("x@y.z, alice@example.com")
    assert rec.queries == ["ali"]


def test_attendee_edit_completes_in_the_middle():
    rec = Recorder()
    edit = make_edit("ali, x@y.z", rec)
    edit._edit.set_edit_pos(2)
    assert edit.keypress((60,), "tab") is None
    assert edit.get_edit_text() == "alice@example.com, x@y.z"


def test_attendee_edit_already_complete_moves_on():
    rec = Recorder()
    edit = make_edit("alice@example.com", rec)
    assert edit.keypress((60,), "tab") == "tab"
    assert edit.get_edit_text() == "alice@example.com"


def test_attendee_edit_no_match():
    rec = Recorder()
    edit = make_edit("zed", rec)
    assert edit.keypress((60,), "tab") == "tab"
    assert edit.get_edit_text() == "zed"
    assert rec.errors == ["No contact found for `zed`"]


def test_attendee_edit_empty_moves_on():
    rec = Recorder()
    edit = make_edit("a@b.c, ", rec)
    assert edit.keypress((60,), "tab") == "tab"
    assert rec.queries == []


def test_attendee_edit_disabled():
    rec = Recorder()
    edit = make_edit("ali", rec, query=False)
    assert edit.keypress((60,), "tab") == "tab"
    assert edit.get_edit_text() == "ali"


def test_attendee_edit_query_error():
    rec = Recorder()

    def broken(pattern):
        raise RuntimeError("boom")

    edit = AttendeeEdit(query=broken, on_error=rec.on_error, edit_text="ali")
    edit._edit.set_edit_pos(3)
    assert edit.keypress((60,), "tab") == "tab"
    assert rec.errors == ["boom"]


def test_attendee_edit_several_matches_pop_up():
    rec = Recorder()
    edit = make_edit("x@y.z, bo", rec)
    opened = []
    edit.open_pop_up = lambda: opened.append(True)
    assert edit.keypress((60,), "tab") is None
    assert opened == [True]
    params = edit.get_pop_up_parameters()
    assert params["left"] == len("Attendees: ")
    assert params["top"] == 1
    assert params["overlay_height"] == 2
    assert params["overlay_width"] == len("< Bob <bob@example.com> >")

    pop_up = edit.create_pop_up()
    pop_up.keypress((30, 2), "tab")  # move to the second candidate
    edit.close_pop_up = lambda: None
    pop_up.keypress((30, 2), "enter")
    assert edit.get_edit_text() == "x@y.z, bo@example.org"


def test_completion_list_esc_closes():
    closed = []
    pop_up = CompletionList(CONTACTS["bo"], on_select=lambda c: None)
    urwid.connect_signal(pop_up, "close", lambda _: closed.append(True))
    assert pop_up.keypress((30, 2), "esc") is None
    assert closed == [True]
