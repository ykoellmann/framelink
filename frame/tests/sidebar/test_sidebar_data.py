from datetime import date

from framelink_frame.sidebar.data import build_data

from sidebar_helpers import entry, mockup

NOV = lambda d: date(2026, 11, 1).fromordinal(date(2026, 11, 1).toordinal() + d - 1)  # Tag des Mockups -> Datum


def data(today=21):
    return build_data(mockup()["entries"], NOV(today))


def test_window_starts_on_monday():
    assert data(21).monday == date(2026, 11, 16)
    assert data(30).monday == date(2026, 11, 30)


def test_day_items_sorted_holiday_birthday_event_observance():
    d = data()
    assert [(i.kind, i.text) for i in d.items(NOV(27))] == [("b", "Oma"), ("e", "Abendessen 18:30")]
    assert [i.kind for i in d.items(NOV(36))] == ["e", "o", "o"]            # Brunch vor 2. Advent, Nikolaus
    assert [i.text for i in d.items(NOV(36))][1:] == ["2. Advent", "Nikolaus"]
    assert d.items(NOV(2)) == ()


def test_holiday_flag_and_school_holiday_tint():
    d = data()
    assert d.is_holiday(NOV(18)) and not d.is_holiday(NOV(19))
    assert all(d.in_school_holiday(NOV(x)) for x in range(16, 21)) and not d.in_school_holiday(NOV(21))


def test_lanes_and_rotating_colours_like_the_mockup():
    spans = {s.title: s for s in data().spans}
    got = [(spans[t].lane, spans[t].color) for t in
           ("Lena im Urlaub", "Papa auf Dienstreise", "Skiurlaub Ute", "Besuch Tante Rita", "Zeltlager Tim", "Kur Opa")]
    assert got == [(0, "r1"), (1, "r2"), (0, "r3"), (1, "r4"), (2, "r1"), (3, "r2")]
    assert spans["Herbstferien"].color == "fer" and spans["Herbstferien"].kind == "f"


def test_lanes_in_window_counts_densest_overlap():
    d = data(30)
    assert d.lanes_in(d.monday, 1) == 1      # Woche 30.11.-6.12.: nur Ski (ab 5.12.)
    assert d.lanes_in(d.monday, 3) == 4      # Dezember 10.-12.: vier Spuren
    assert data(21).lanes_in(NOV(16), 1) == 0


def test_pill_only_in_week_where_entry_begins_or_first_block():
    d = data(21)
    assert [s.title for s in d.pills_in(NOV(16))] == ["Herbstferien"]
    assert [s.title for s in d.pills_in(NOV(23))] == ["Lena im Urlaub", "Papa auf Dienstreise"]
    assert d.pills_in(NOV(30)) and [s.title for s in d.pills_in(NOV(30))] == ["Skiurlaub Ute"]
    # Eintrag, der vor dem Fenster begann: Pill im ersten sichtbaren Block, nicht im zweiten
    d2 = build_data([entry("vacation", "Lang", "2026-11-10", "2026-11-25")], date(2026, 11, 21))
    assert [s.title for s in d2.pills_in(date(2026, 11, 16))] == ["Lang"]
    assert d2.pills_in(date(2026, 11, 23)) == []


def test_today_items_events_then_running_spans():
    d = build_data([entry("birthday", "Oma", "2026-11-27"), entry("vacation", "Urlaub", "2026-11-25", "2026-11-29"),
                    entry("school_holiday", "Ferien", "2026-11-20", "2026-12-01"), entry("appointment", "Morgen", "2026-11-28")],
                   date(2026, 11, 27))
    assert [(i.kind, i.text) for i in d.today_items()] == [("b", "Oma"), ("f", "Ferien"), ("v", "Urlaub")]   # Spannen nach Start


def test_time_is_appended_for_timed_entries_and_garbage_is_skipped():
    d = build_data([entry("appointment", "Zahnarzt", "2026-11-21", all_day=False, time="14:00"),
                    {"kind": "appointment", "title": "kaputt", "start": "kein Datum"}, {"title": "ohne Start"},
                    entry("appointment", "   ", "2026-11-21"), entry("appointment", "Alt", "2020-01-01")], date(2026, 11, 21))
    assert [i.text for i in d.items(date(2026, 11, 21))] == ["Zahnarzt 14:00"]


def test_multi_day_regular_entries_show_on_each_day_and_order_is_deterministic():
    es = [entry("holiday", "Tag A", "2026-11-23", "2026-11-24"), entry("holiday", "Tag B", "2026-11-23")]
    a = build_data(es, date(2026, 11, 21))
    b = build_data(list(reversed(es)), date(2026, 11, 21))
    assert a.days == b.days
    assert [i.text for i in a.items(date(2026, 11, 24))] == ["Tag A"]
    assert [i.text for i in a.items(date(2026, 11, 23))] == ["Tag A", "Tag B"]
