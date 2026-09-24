from scripts.record_draft_groups import _sorted_overrides, merge_discovery


def _live(gid, label="L"):
    return {"draft_group_id": gid, "label": label, "source": "live"}


def test_records_live_salaried_groups_for_a_new_week():
    overrides = {"_readme": "x", "2026": {"1": {"classic": {"draft_group_id": 1, "label": "W1"}}}}
    discovery = {"classic": _live(153768, "C"), "showdown": {"THU_NIGHT": _live(153775, "T")}}
    report = merge_discovery(overrides, 2026, 3, discovery, lambda gid, t: True)

    assert overrides["2026"]["3"] == {
        "classic": {"draft_group_id": 153768, "label": "C"},
        "showdown": {"THU_NIGHT": {"draft_group_id": 153775, "label": "T"}},
    }
    assert overrides["2026"]["1"]["classic"]["draft_group_id"] == 1
    assert report == ["classic_sunday: not in DraftKings' live listing (kept nothing)", "classic: recorded 153768", "showdown THU_NIGHT: recorded 153775"]


def test_skips_groups_without_salaries_and_non_live_sources():
    overrides = {}
    discovery = {
        "classic": _live(146138),
        "showdown": {"SUN_NIGHT": {"draft_group_id": None, "label": "S", "source": "unavailable"}},
    }
    report = merge_discovery(overrides, 2026, 4, discovery, lambda gid, t: False)

    assert "4" not in overrides.get("2026", {})
    assert report[1] == "classic: group 146138 has no salaries yet, not recorded"
    assert report[2].startswith("showdown SUN_NIGHT: not in DraftKings' live listing")


def test_rerun_is_a_no_op_and_changed_ids_are_updated():
    overrides = {"2026": {"3": {"classic": {"draft_group_id": 153768, "label": "C"}}}}
    same = merge_discovery(overrides, 2026, 3, {"classic": _live(153768, "C"), "showdown": {}}, lambda g, t: True)
    assert same == ["classic_sunday: not in DraftKings' live listing (kept nothing)", "classic: 153768 already recorded"]

    changed = merge_discovery(overrides, 2026, 3, {"classic": _live(160000, "C"), "showdown": {}}, lambda g, t: True)
    assert changed == ["classic_sunday: not in DraftKings' live listing (kept nothing)", "classic: recorded 160000 (was 153768)"]
    assert overrides["2026"]["3"]["classic"]["draft_group_id"] == 160000


def test_keeps_an_already_recorded_week_once_it_leaves_the_live_listing():
    overrides = {"2026": {"3": {"classic": {"draft_group_id": 153768, "label": "C"}}}}
    report = merge_discovery(overrides, 2026, 3, {"classic": None, "showdown": {}}, lambda g, t: True)
    assert overrides["2026"]["3"]["classic"]["draft_group_id"] == 153768
    assert report == ["classic_sunday: not in DraftKings' live listing (kept nothing)", "classic: not in DraftKings' live listing (kept 153768)"]


def test_sorted_overrides_orders_weeks_numerically_and_keeps_readme_first():
    out = _sorted_overrides({"2026": {"10": {}, "3": {}, "1": {}}, "_readme": "x"})
    assert list(out) == ["_readme", "2026"]
    assert list(out["2026"]) == ["1", "3", "10"]


def test_records_the_sunday_main_slate_with_its_kickoff_window():
    overrides = {}
    sunday = {**_live(153769, "Classic - Sunday Main (13 games)"),
              "first_kickoff": "2026-09-27T17:00:00+00:00", "last_kickoff": "2026-09-27T20:25:00+00:00"}
    report = merge_discovery(overrides, 2026, 3, {"classic_sunday": sunday, "classic": None, "showdown": {}}, lambda g, t: True)
    assert overrides["2026"]["3"]["classic_sunday"] == {k: v for k, v in sunday.items() if k != "source"}
    assert report[0] == "classic_sunday: recorded 153769"
