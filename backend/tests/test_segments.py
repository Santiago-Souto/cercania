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


WORDS = [  # Groq word timestamps from a fictional test note
    {"start": 7.84, "end": 7.98, "text": "A"}, {"start": 7.98, "end": 8.12, "text": "la"},
    {"start": 8.12, "end": 8.40, "text": "noche"}, {"start": 8.40, "end": 8.88, "text": "durmió"},
    {"start": 8.88, "end": 9.36, "text": "mal,"}, {"start": 9.36, "end": 9.60, "text": "se"},
    {"start": 9.60, "end": 10.16, "text": "despertó"},
]


def test_word_level_pieces_give_the_exact_range():
    assert quote_times("durmió mal", WORDS) == (8.40, 9.36)
    assert quote_times("A la noche durmió mal, se despertó", WORDS) == (7.84, 10.16)


def test_long_transcripts_stay_fast():
    import time

    words = [{"start": i * 0.3, "end": i * 0.3 + 0.3, "text": f"palabra{i}"} for i in range(2000)]
    t0 = time.perf_counter()
    assert quote_times("palabra1500 palabra1501", words) == (450.0, 450.6)
    assert quote_times("no esta en el audio", words) == (None, None)
    assert time.perf_counter() - t0 < 0.5
