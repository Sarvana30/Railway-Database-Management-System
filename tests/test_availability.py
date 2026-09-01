"""Pure-python unit tests -- no DB needed -- for the two logic-only functions
in app/services/availability.py: segments_overlap and
find_adjacent_available_seats.
"""
from app.services.availability import segments_overlap, find_adjacent_available_seats


def test_identical_ranges_overlap():
    assert segments_overlap(1, 5, 1, 5) is True


def test_disjoint_adjacent_ranges_do_not_overlap():
    # A->C (1..3) and C->B (3..6): they touch at the boundary stop but don't
    # occupy the seat at the same time -- this is exactly Feature 4's rule.
    assert segments_overlap(1, 3, 3, 6) is False


def test_disjoint_far_apart_ranges_do_not_overlap():
    assert segments_overlap(1, 2, 5, 6) is False


def test_partial_overlap_is_detected():
    assert segments_overlap(1, 4, 3, 6) is True


def test_containment_is_detected():
    assert segments_overlap(1, 10, 3, 5) is True


def _row(coach, status):
    return {"coach_number": coach, "status": status, "seat": None}


def test_adjacent_seats_found_within_one_coach():
    rows = [
        _row("A1", "available"),
        _row("A1", "available"),
        _row("A1", "booked"),
        _row("A1", "available"),
    ]
    group = find_adjacent_available_seats(rows, 2)
    assert group is not None
    assert len(group) == 2
    assert all(r["coach_number"] == "A1" for r in group)


def test_adjacent_seats_do_not_cross_coach_boundary():
    rows = [
        _row("A1", "available"),
        _row("A2", "available"),
        _row("A2", "available"),
    ]
    group = find_adjacent_available_seats(rows, 2)
    assert group is not None
    assert group[0]["coach_number"] == "A2"
    assert group[1]["coach_number"] == "A2"


def test_no_adjacent_group_returns_none():
    rows = [_row("A1", "available"), _row("A1", "booked"), _row("A1", "available")]
    assert find_adjacent_available_seats(rows, 2) is None


def test_group_size_one_returns_first_available():
    rows = [_row("A1", "booked"), _row("A1", "available")]
    group = find_adjacent_available_seats(rows, 1)
    assert len(group) == 1
    assert group[0]["status"] == "available"
