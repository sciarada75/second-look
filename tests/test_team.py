"""A role can only make Second Look stricter; over a person's limit the case passes on. Run: python3 tests/test_team.py"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from secondlook import team  # noqa: E402

T = {"roles": {"Head of customer care": {"refund_up_to": None}, "Customer care assistant": {"refund_up_to": 30.0},
               "Trainee": {}},
     "people": [{"id": "giulia", "name": "Giulia", "role": "Head of customer care"},
                {"id": "marta", "name": "Marta", "role": "Customer care assistant"},
                {"id": "nico", "name": "Nico", "role": "Trainee"}]}


def test_a_person_may_send_money_up_to_their_role_and_no_further():
    assert team.covers(T, "marta", 30.0) and not team.covers(T, "marta", 30.01)
    assert team.covers(T, "giulia", 10_000)          # no cap of the role's own
    assert not team.covers(T, "nico", 0.01)          # a role with no limit written sends no money
    assert not team.covers(T, "stranger", 1)         # not in the team: nothing


def test_over_the_limit_the_case_goes_to_the_first_colleague_who_may_send_it():
    assert team.handoff_to(T, 89.0, exclude="marta")["id"] == "giulia"
    only_agents = {"roles": T["roles"], "people": [T["people"][1], {"id": "luca", "name": "Luca", "role": "Customer care assistant"}]}
    assert team.handoff_to(only_agents, 89.0, exclude="marta") is None


def test_no_team_block_means_a_team_of_one_with_full_rights():
    solo = team.of(None)
    assert solo["solo"] and team.person(solo, None)["name"] == "You" and team.covers(solo, "you", 5_000)
    assert team.of(T) == T and team.person(T, None) is None   # in a team, nobody is assumed


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
    bare = {"people": [{"id": "marta", "name": "Marta", "role": "Customer care assistant"}]}
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


def test_a_malformed_team_file_never_crashes_and_never_sends_money():
    shapes = [{"roles": {"A": {"refund_up_to": 30.0}}, "people": ["marta"]},
              {"roles": {"A": 30}, "people": [{"id": "marta", "role": "A"}]},
              {"roles": ["A"], "people": [{"id": "marta", "role": "A"}]},
              {"roles": {"A": {"refund_up_to": 30.0}}, "people": {"marta": {"role": "A"}}},
              {"roles": {"A": {"refund_up_to": 30.0}}, "people": [{"id": "marta", "role": ["A"]}]}]
    for t in shapes:
        assert not team.covers(t, "marta", 1) and team.handoff_to(t, 1, exclude=None) is None, t


def test_an_unreadable_store_is_never_overwritten():
    import os
    path = Path(tempfile.mkdtemp()) / "a.json"
    path.write_text('{"D1": {"to": "marta"}}')
    os.chmod(path, 0)
    try:
        store = team.Assignments(path)
        try:
            store.assign("D2", "giulia")
        except OSError:
            pass
        else:
            raise AssertionError("wrote over a store it could not read")
    finally:
        os.chmod(path, 0o600)
    assert path.read_text() == '{"D1": {"to": "marta"}}'


def test_update_changes_one_case_from_its_current_state():
    store = team.Assignments(Path(tempfile.mkdtemp()) / "a.json", seed={"D1": {"to": "marta"}})
    store.update("D1", lambda a: {**a, "handoff": {"from": a["to"], "amount": 89.0}})
    assert store.get("D1") == {"to": "marta", "handoff": {"from": "marta", "amount": 89.0}}
    store.update("D9", lambda a: {**a, "to": "nico"})
    assert store.get("D9") == {"to": "nico", "handoff": None}


def test_no_name_never_matches_an_entry_without_an_id():
    t = team.of({"people": [{"name": "no id", "role": "Boss"}], "roles": {"Boss": {"refund_up_to": None}}})
    assert team.person(t, None) is None and team.person(t, "") is None and team.first(t) is None


def test_outside_data_can_t_claim_to_be_a_team_of_one():
    t = team.of({"people": [{"id": "m", "name": "M", "role": "R"}], "roles": {"R": {"refund_up_to": 10}}, "solo": True})
    assert not t.get("solo") and team.person(t, None) is None


def test_a_json_file_changes_under_one_lock_and_keeps_a_broken_file_aside():
    path = Path(tempfile.mkdtemp()) / "c.json"
    f = team.JsonFile(path)
    assert f.snapshot() == {} and f.transact(lambda d: d.setdefault("n", 1)) == 1
    f.transact(lambda d: d.update(n=d["n"] + 1))
    assert team.JsonFile(path).snapshot() == {"n": 2}

    def half_done(d):
        d["n"] = 99
        raise ValueError("stopped half-way")
    try:
        f.transact(half_done)
    except ValueError:
        pass
    assert f.snapshot() == {"n": 2}                      # a change that failed half-way is never written
    path.write_text("[1, 2]")
    assert f.snapshot() == {} and (path.parent / "c.json.corrupt").read_text() == "[1, 2]"

def test_a_store_touched_from_inside_its_own_change_says_so_instead_of_hanging():
    import threading
    path = Path(tempfile.mkdtemp()) / "c.json"
    f = team.JsonFile(path)
    f.transact(lambda d: d.update(n=1))
    got = []

    def nested():
        try:
            f.transact(lambda d: f.snapshot())
        except RuntimeError as err:
            got.append(str(err))
    t = threading.Thread(target=nested, daemon=True)
    t.start()
    t.join(3)
    assert not t.is_alive(), "a change that read the store again waited on itself for ever"
    assert got and "inside" in got[0]
    assert f.snapshot() == {"n": 1}                                        # the lock is free again, nothing written


if __name__ == "__main__":
    fns = [v for k, v in dict(globals()).items() if k.startswith("test_")]
    for f in fns:
        f(); print("ok ", f.__name__)
    print(f"{len(fns)} passed")
