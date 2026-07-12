from majak.ingest.merge import CARRY_THRESHOLD, blended_score, cosine, lexical_similarity


def test_lexical_similarity_ignores_accents_and_case():
    assert lexical_similarity("Poslať faktúru", "poslat fakturu") == 1.0


def test_same_task_is_a_carry_over():
    score = lexical_similarity(
        "Poslať faktúru klientovi Acme", "poslat fakturu klientovi acme s.r.o."
    )
    assert score >= CARRY_THRESHOLD


def test_unrelated_tasks_do_not_carry():
    score = lexical_similarity("Poslať faktúru", "Naplánovať teambuilding")
    assert score < CARRY_THRESHOLD


def test_cosine_basic():
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine(None, [1, 0]) is None
    assert cosine([1, 0], [1, 0, 0]) is None


def test_blended_score_uses_lexical_when_no_embedding():
    assert blended_score("a task", "a task", None) == lexical_similarity("a task", "a task")


def test_blended_score_averages_with_embedding():
    s = blended_score("a task", "different", 1.0)
    lex = lexical_similarity("a task", "different")
    # blended_score rounds to 4 dp.
    assert abs(s - (0.5 * lex + 0.5)) < 1e-3
