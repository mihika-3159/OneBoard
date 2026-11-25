"""The council must not silently exclude selected specialists from debate."""
from apps.api.services.council_engine import specialist_challenge_pairs, COUNCIL_ROLES


def test_all_selected_specialists_appear_in_challenge_pairs():
    selected = list(COUNCIL_ROLES)
    pairs = specialist_challenge_pairs(selected)
    specialists = [name for name in selected if name != "Chief of Staff"]
    assert len(pairs) == len(specialists) - 1
    assert {name for pair in pairs for name in pair} == set(specialists)


def test_challenge_pairs_follow_selection_order_and_exclude_facilitator():
    assert specialist_challenge_pairs([
        "Marketing Adviser", "Chief of Staff", "Finance Adviser", "Technology Adviser"
    ]) == [
        ("Marketing Adviser", "Finance Adviser"),
        ("Finance Adviser", "Technology Adviser"),
    ]


def test_single_specialist_does_not_generate_a_fictitious_debate():
    assert specialist_challenge_pairs(["Chief of Staff", "Finance Adviser"]) == []
    assert specialist_challenge_pairs(["Chief of Staff"]) == []
