"""Tests for hipaasynth.aast.adapter: one adapter for every model output type.

Each output type must map to the same normalised ModelResponse, refusals and
unreadable text must be counted (never guessed), and a wrong-typed answer from a
structured model must raise instead of being silently miscounted.
"""

import math

import pytest

from hipaasynth.aast import OUTPUT_TYPES, ModelAdapter, ModelResponse, parse_final_answer


def _const(value):
    return lambda case: value


# --- binary -----------------------------------------------------------------


@pytest.mark.parametrize("value", [True, False])
def test_binary_passes_through(value):
    r = ModelAdapter(_const(value), "binary").respond({})
    assert r == ModelResponse(decision=value, raw=repr(value))
    assert r.answered


@pytest.mark.parametrize("value", [1, 0, "yes", "no", 0.9])
def test_binary_rejects_non_bool(value):
    with pytest.raises(TypeError, match="binary"):
        ModelAdapter(_const(value), "binary").respond({})


# --- score ------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, decision",
    [(5.99, False), (6, True), (6.0, True), (87, True), (0, False)],
)
def test_score_uses_deployed_threshold(score, decision):
    # Epic Sepsis Model style: 0-100 score, site alerts at 6.
    r = ModelAdapter(_const(score), "score", threshold=6).respond({})
    assert r.decision is decision
    assert r.score == float(score)


def test_score_lower_is_positive():
    adapter = ModelAdapter(_const(0.2), "score", threshold=0.3, higher_is_positive=False)
    assert adapter.respond({}).decision is True


@pytest.mark.parametrize("value", ["0.7", True, [0.7]])
def test_score_rejects_non_number(value):
    with pytest.raises(TypeError, match="score"):
        ModelAdapter(_const(value), "score", threshold=0.5).respond({})


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_score_rejects_non_finite(value):
    with pytest.raises(ValueError, match="finite"):
        ModelAdapter(_const(value), "score", threshold=0.5).respond({})


def test_score_requires_threshold():
    with pytest.raises(ValueError, match="threshold"):
        ModelAdapter(_const(0.5), "score")


@pytest.mark.parametrize("threshold", [math.nan, "6", True])
def test_score_rejects_bad_threshold(threshold):
    with pytest.raises(ValueError, match="threshold"):
        ModelAdapter(_const(0.5), "score", threshold=threshold)


# --- ordinal ----------------------------------------------------------------


@pytest.mark.parametrize("level, decision", [(1, True), (2, True), (3, False), (5, False)])
def test_ordinal_esi_acute_levels(level, decision):
    r = ModelAdapter(_const(level), "ordinal", acute_levels={1, 2}).respond({})
    assert r.decision is decision
    assert r.level == level


@pytest.mark.parametrize("value", ["2", 2.0, True])
def test_ordinal_rejects_non_int(value):
    with pytest.raises(TypeError, match="ordinal"):
        ModelAdapter(_const(value), "ordinal", acute_levels={1, 2}).respond({})


@pytest.mark.parametrize("levels", [None, set(), {1.5}, {True}])
def test_ordinal_requires_int_levels(levels):
    with pytest.raises(ValueError, match="acute_levels"):
        ModelAdapter(_const(1), "ordinal", acute_levels=levels)


# --- ranked -----------------------------------------------------------------


DIFFERENTIAL = ["Urinary tract infection", "Sepsis", "Pyelonephritis"]


@pytest.mark.parametrize("k, decision", [(1, False), (2, True), (3, True)])
def test_ranked_top_k(k, decision):
    r = ModelAdapter(_const(DIFFERENTIAL), "ranked", k=k).respond({}, target="sepsis")
    assert r.decision is decision
    assert r.rank == 2


def test_ranked_target_absent_is_a_miss_not_an_abstention():
    r = ModelAdapter(_const(DIFFERENTIAL), "ranked", k=3).respond({}, target="Fabry disease")
    assert r.decision is False and r.rank is None and not r.abstained


def test_ranked_label_match_ignores_case_and_spacing():
    r = ModelAdapter(_const(["  ACUTE   Stroke "]), "ranked", k=1).respond(
        {}, target="acute stroke"
    )
    assert r.decision is True


def test_ranked_requires_target():
    with pytest.raises(ValueError, match="target"):
        ModelAdapter(_const(DIFFERENTIAL), "ranked", k=3).respond({})


@pytest.mark.parametrize("value", ["Sepsis", [1, 2], b"Sepsis"])
def test_ranked_rejects_non_label_lists(value):
    with pytest.raises(TypeError, match="ranked"):
        ModelAdapter(_const(value), "ranked", k=3).respond({}, target="Sepsis")


@pytest.mark.parametrize("k", [None, 0, 1.0, True])
def test_ranked_requires_positive_int_k(k):
    with pytest.raises(ValueError, match="k"):
        ModelAdapter(_const([]), "ranked", k=k)


# --- text -------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, decision",
    [
        ("Lactate 4.1, MAP 58.\nFINAL_ANSWER: Yes", True),
        ("Vitals stable.\nfinal_answer : no", False),
        # The last terminator wins, so a model that revises itself is read correctly.
        ("FINAL_ANSWER: No ... on reflection\nFINAL_ANSWER: Yes", True),
    ],
)
def test_text_parses_final_answer(text, decision):
    r = ModelAdapter(_const(text), "text").respond("prompt")
    assert r.decision is decision and not r.parse_failed and not r.abstained


def test_text_without_terminator_is_parse_failed_not_guessed():
    # Prose that says "yes" must not be read as a decision.
    r = ModelAdapter(_const("Yes, sepsis is possible but I would want more data."), "text").respond(
        "prompt"
    )
    assert r.decision is None and r.parse_failed and not r.abstained and not r.answered


def test_text_refusal_is_abstained():
    r = ModelAdapter(_const("Insufficient data.\nFINAL_ANSWER: Unsure"), "text").respond("prompt")
    assert r.decision is None and r.abstained and not r.parse_failed


def test_text_custom_parser_and_abstain_patterns():
    adapter = ModelAdapter(
        _const("RECOMMEND: escalate"),
        "text",
        parser=lambda s: True if "escalate" in s else None,
        abstain_patterns=[r"I cannot provide medical advice"],
    )
    assert adapter.respond("p").decision is True
    refusal = ModelAdapter(
        _const("I cannot provide medical advice."),
        "text",
        abstain_patterns=[r"I cannot provide medical advice"],
    )
    assert refusal.respond("p").abstained


def test_text_parser_must_return_bool_or_none():
    adapter = ModelAdapter(_const("x"), "text", parser=lambda s: "yes")
    with pytest.raises(TypeError, match="parser"):
        adapter.respond("p")


def test_text_never_sets_a_score():
    # Verbalised LLM confidence is not a model-native score.
    r = ModelAdapter(_const("I am 92% confident.\nFINAL_ANSWER: Yes"), "text").respond("p")
    assert r.score is None


def test_text_rejects_non_string():
    with pytest.raises(TypeError, match="text"):
        ModelAdapter(_const(True), "text").respond("p")


def test_parse_final_answer_direct():
    assert parse_final_answer("FINAL_ANSWER: YES") is True
    assert parse_final_answer("no terminator") is None


# --- all types --------------------------------------------------------------


_SETTINGS = {
    "binary": {},
    "score": {"threshold": 0.5},
    "ordinal": {"acute_levels": {1}},
    "ranked": {"k": 1},
    "text": {},
}


@pytest.mark.parametrize("output", OUTPUT_TYPES)
def test_none_is_an_abstention_for_every_type(output):
    r = ModelAdapter(_const(None), output, **_SETTINGS[output]).respond({}, target="x")
    assert r.decision is None and r.abstained and not r.parse_failed


@pytest.mark.parametrize("output", OUTPUT_TYPES)
def test_describe_has_one_fixed_layout(output):
    desc = ModelAdapter(_const(None), output, name="m", **_SETTINGS[output]).describe()
    assert list(desc) == [
        "name",
        "output",
        "threshold",
        "higher_is_positive",
        "acute_levels",
        "k",
        "parser",
        "abstain_patterns",
    ]
    assert desc["output"] == output and desc["name"] == "m"


def test_describe_is_stable_across_instances():
    a = ModelAdapter(_const(1), "ordinal", acute_levels=[2, 1]).describe()
    b = ModelAdapter(_const(1), "ordinal", acute_levels={1, 2}).describe()
    assert a == b and a["acute_levels"] == [1, 2]


@pytest.mark.parametrize(
    "output, extra",
    [
        ("binary", {"threshold": 0.5}),
        ("score", {"threshold": 0.5, "k": 3}),
        ("ordinal", {"acute_levels": {1}, "parser": parse_final_answer}),
        ("text", {"acute_levels": {1}}),
    ],
)
def test_settings_for_another_type_are_rejected(output, extra):
    with pytest.raises(ValueError, match="does not apply"):
        ModelAdapter(_const(None), output, **extra)


def test_unknown_output_type():
    with pytest.raises(ValueError, match="output must be one of"):
        ModelAdapter(_const(None), "probability")


def test_fn_must_be_callable():
    with pytest.raises(TypeError, match="callable"):
        ModelAdapter(0.5, "binary")


def test_model_receives_the_case_unchanged():
    seen = []
    ModelAdapter(lambda case: seen.append(case) or True, "binary").respond({"id": 7})
    assert seen == [{"id": 7}]
