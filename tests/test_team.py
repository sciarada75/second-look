"""A role can only make Second Look stricter; over a person's limit the case passes on. Run: python3 tests/test_team.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import team  # noqa: E402

T = {"roles": {"Customer care manager": {"refund_up_to": None}, "Customer care agent": {"refund_up_to": 30.0},
               "Trainee": {}},
     "people": [{"id": "giulia", "name": "Giulia", "role": "Customer care manager"},
                {"id": "marta", "name": "Marta", "role": "Customer care agent"},
                {"id": "nico", "name": "Nico", "role": "Trainee"}]}


def test_a_person_may_send_money_up_to_their_role_and_no_further():
    assert team.covers(T, "marta", 30.0) and not team.covers(T, "marta", 30.01)
    assert team.covers(T, "giulia", 10_000)          # no cap of the role's own
    assert not team.covers(T, "nico", 0.01)          # a role with no limit written sends no money
    assert not team.covers(T, "stranger", 1)         # not in the team: nothing


def test_over_the_limit_the_case_goes_to_the_first_colleague_who_may_send_it():
    assert team.handoff_to(T, 89.0, exclude="marta")["id"] == "giulia"
    only_agents = {"roles": T["roles"], "people": [T["people"][1], {"id": "luca", "name": "Luca", "role": "Customer care agent"}]}
    assert team.handoff_to(only_agents, 89.0, exclude="marta") is None


def test_no_team_block_means_a_team_of_one_with_full_rights():
    solo = team.of(None)
    assert solo["solo"] and team.person(solo, None)["name"] == "You" and team.covers(solo, "you", 5_000)
    assert team.of(T) is T and team.person(T, None) is None   # in a team, nobody is assumed


def test_assignments_are_kept_per_case_and_seeded_once():
    store = team.Assignments(Path(tempfile.mkdtemp()) / "a.json", seed={"D1": {"to": "marta"}})
    assert store.get("D1")["to"] == "marta" and store.get("D2") == {"to": None, "handoff": None}
    store.assign("D2", "giulia", handoff={"from": "marta", "action": "REFUND", "amount": 89.0})
    again = team.Assignments(store.path, seed={"D1": {"to": "luca"}})   # the file exists: the seed is ignored
    assert again.get("D1")["to"] == "marta" and again.get("D2")["handoff"]["from"] == "marta"


def test_a_limit_that_is_not_a_number_sends_no_money():
    odd = {"roles": {"A": {"refund_up_to": "30"}, "B": {"refund_up_to": "lots"}, "C": {"refund_up_to": True}},
           "people": [{"id": "a", "name": "A", "role": "A"}, {"id": "b", "name": "B", "role": "B"},
                      {"id": "c", "name": "C", "role": "C"}]}
    for pid in ("a", "b", "c"):
        assert team.limit(odd, pid) == 0.0 and not team.covers(odd, pid, 1), pid


def test_a_team_without_roles_does_not_crash_and_sends_nothing():
    bare = {"people": [{"id": "marta", "name": "Marta", "role": "Customer care agent"}]}
    assert not team.covers(bare, "marta", 1) and team.handoff_to(bare, 1, exclude=None) is None


def test_the_team_of_one_is_a_fresh_copy():
    team.of(None)["people"][0]["role"] = "Trainee"
    assert team.of(None)["people"][0]["role"] == "Owner"


def test_a_corrupt_assignments_file_is_kept_aside_never_overwritten():
    path = Path(tempfile.mkdtemp()) / "a.json"
    path.write_text("{not json")
    store = team.Assignments(path)
    assert store.all() == {} and store.get("D1") == {"to": None, "handoff": None}
    assert (path.parent / "a.json.corrupt").read_text() == "{not json"
    store.assign("D1", "marta")
    assert team.Assignments(path).get("D1")["to"] == "marta"
    assert (path.parent / "a.json.corrupt").read_text() == "{not json"


def test_all_returns_every_case_in_the_same_shape_as_get():
    path = Path(tempfile.mkdtemp()) / "a.json"
    path.write_text('{"D1": {"to": "marta", "extra": 1}, "D2": "junk"}')
    assert team.Assignments(path).all() == {"D1": {"to": "marta", "handoff": None},
                                            "D2": {"to": None, "handoff": None}}


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
