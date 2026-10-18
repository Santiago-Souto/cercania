from app.segments import quote_times

SEGMENTS = [
    {"start": 0.0, "end": 3.5, "text": "Anoche le di la medicación de las ocho."},
    {"start": 3.5, "end": 6.0, "text": "Comió poco en la cena."},
    {"start": 6.0, "end": 8.0, "text": "Durmió bien."},
]


def test_quote_inside_one_segment():
    assert quote_times("comio poco en la cena", SEGMENTS) == (3.5, 6.0)


def test_quote_across_consecutive_segments_spans_them():
    assert quote_times("las ocho. Comió poco", SEGMENTS) == (0.0, 6.0)
    assert quote_times("ocho comió poco en la cena durmió", SEGMENTS) == (0.0, 8.0)


def test_shortest_run_wins():
    segments = [
        {"start": 0.0, "end": 2.0, "text": "Hoy"},
        {"start": 2.0, "end": 4.0, "text": "durmió bien."},
        {"start": 4.0, "end": 6.0, "text": "Durmió bien la siesta."},
    ]
    assert quote_times("durmió bien la siesta", segments) == (4.0, 6.0)
    assert quote_times("durmió bien", segments) == (2.0, 4.0)  # first of two equal runs


def test_whole_words_only():
    assert quote_times("mio poco", SEGMENTS) == (None, None)


def test_no_match_no_segments_or_no_quote():
    assert quote_times("se cayó en el baño", SEGMENTS) == (None, None)
    assert quote_times("Durmió bien", []) == (None, None)
    assert quote_times("Durmió bien", None) == (None, None)
    assert quote_times(None, SEGMENTS) == (None, None)
    assert quote_times("  ", SEGMENTS) == (None, None)
