import itertools

import pytest
from hypothesis import assume, given, settings
from hypothesis import strategies as st

from mahjong_core.actions import ClaimChow, ClaimKong, ClaimPung, ClaimWin, Pass
from mahjong_core.claims import ClaimResponse, can_close_early, resolve_claims
from mahjong_core.melds import Meld, MeldKind
from mahjong_core.state import ClaimKind, ClaimOffer, ClaimWindow
from mahjong_core.tiles import TileType, tile_ids_for_type

_MAN_1 = tile_ids_for_type(TileType.MAN_1)
_MAN_2 = tile_ids_for_type(TileType.MAN_2)
_MAN_3 = tile_ids_for_type(TileType.MAN_3)
_MAN_4 = tile_ids_for_type(TileType.MAN_4)
_MAN_5 = tile_ids_for_type(TileType.MAN_5)

_CHOW = Meld(MeldKind.CHOW, (_MAN_1[0], _MAN_2[0], _MAN_3[0]), from_seat=0)
_PUNG = Meld(MeldKind.PUNG, tuple(_MAN_4[:3]), from_seat=0)
_KONG = Meld(MeldKind.EXPOSED_KONG, tuple(_MAN_5), from_seat=0)


def _window(source_seat: int, offers: tuple[ClaimOffer, ...], window_id: int = 1) -> ClaimWindow:
    return ClaimWindow(
        window_id=window_id,
        kind=ClaimKind.DISCARD,
        source_seat=source_seat,
        tile=_MAN_1[0],
        offers=offers,
    )


# --- resolve_claims: priority order (01-rules-spec.md §6) -----------------------------------


def test_all_pass_produces_no_winner() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=True, melds=(_CHOW,)),))
    responses = {1: Pass(window_id=1, seat=1)}
    result = resolve_claims(window, responses)
    assert result.winning_seat is None
    assert result.action is None


def test_missing_response_treated_as_pass() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=True, melds=(_CHOW,)),))
    result = resolve_claims(window, {})
    assert result.winning_seat is None


def test_win_beats_pung() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_PUNG,)),
            ClaimOffer(seat=2, can_win=True),
        ),
    )
    responses: dict[int, ClaimResponse] = {
        1: ClaimPung(window_id=1, seat=1, meld=_PUNG),
        2: ClaimWin(window_id=1, seat=2),
    }
    result = resolve_claims(window, responses)
    assert result.winning_seat == 2
    assert isinstance(result.action, ClaimWin)


def test_win_beats_kong() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_KONG,)),
            ClaimOffer(seat=3, can_win=True),
        ),
    )
    responses: dict[int, ClaimResponse] = {
        1: ClaimKong(window_id=1, seat=1, meld=_KONG),
        3: ClaimWin(window_id=1, seat=3),
    }
    result = resolve_claims(window, responses)
    assert result.winning_seat == 3
    assert isinstance(result.action, ClaimWin)


def test_pung_beats_chow() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_CHOW,)),
            ClaimOffer(seat=2, can_win=False, melds=(_PUNG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {
        1: ClaimChow(window_id=1, seat=1, meld=_CHOW),
        2: ClaimPung(window_id=1, seat=2, meld=_PUNG),
    }
    result = resolve_claims(window, responses)
    assert result.winning_seat == 2
    assert isinstance(result.action, ClaimPung)


def test_kong_beats_chow() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_CHOW,)),
            ClaimOffer(seat=3, can_win=False, melds=(_KONG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {
        1: ClaimChow(window_id=1, seat=1, meld=_CHOW),
        3: ClaimKong(window_id=1, seat=3, meld=_KONG),
    }
    result = resolve_claims(window, responses)
    assert result.winning_seat == 3
    assert isinstance(result.action, ClaimKong)


def test_kong_beats_pung_different_seats() -> None:
    """01-rules-spec.md §6 point 2: the kong-vs-pung edge case. Structurally unreachable in
    a real deal (see the note added to §6 point 5 -- a kong claim already accounts for all 3
    copies left after the discard) but resolve_claims still implements the ordering."""
    window = _window(
        0,
        (
            ClaimOffer(seat=2, can_win=False, melds=(_PUNG,)),
            ClaimOffer(seat=3, can_win=False, melds=(_KONG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {
        2: ClaimPung(window_id=1, seat=2, meld=_PUNG),
        3: ClaimKong(window_id=1, seat=3, meld=_KONG),
    }
    result = resolve_claims(window, responses)
    assert result.winning_seat == 3
    assert isinstance(result.action, ClaimKong)


def test_same_seat_pung_and_kong_own_choice_is_not_a_tiebreak() -> None:
    """melds.py: a holder of 3 concealed matches gets both options as its own choice, not a
    cross-seat tiebreak. Whichever it submits simply wins outright (no other contender)."""
    window = _window(0, (ClaimOffer(seat=2, can_win=False, melds=(_PUNG, _KONG)),))
    responses: dict[int, ClaimResponse] = {2: ClaimPung(window_id=1, seat=2, meld=_PUNG)}
    result = resolve_claims(window, responses)
    assert result.winning_seat == 2
    assert isinstance(result.action, ClaimPung)


@pytest.mark.parametrize(
    "win_seat,source_seat,other_win_seats,expected_winner",
    [
        (1, 0, (3,), 1),  # seat 1 is closer to discarder 0 than seat 3
        (3, 0, (1,), 1),
        (2, 1, (0,), 2),  # wraps around: (0-1)%4=3 > (2-1)%4=1
    ],
)
def test_win_vs_win_tiebreak_by_seat_order(
    win_seat: int, source_seat: int, other_win_seats: tuple[int, ...], expected_winner: int
) -> None:
    seats = {win_seat, *other_win_seats}
    window = _window(source_seat, tuple(ClaimOffer(seat=s, can_win=True) for s in sorted(seats)))
    responses: dict[int, ClaimResponse] = {s: ClaimWin(window_id=1, seat=s) for s in seats}
    result = resolve_claims(window, responses)
    assert result.winning_seat == expected_winner


def test_resolve_claims_rejects_response_from_unoffered_seat() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=True),))
    with pytest.raises(ValueError):
        resolve_claims(window, {2: ClaimWin(window_id=1, seat=2)})


def test_resolve_claims_rejects_seat_key_mismatch() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=True),))
    with pytest.raises(ValueError):
        resolve_claims(window, {1: ClaimWin(window_id=1, seat=2)})


def test_resolve_claims_rejects_stale_window_id() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=True),), window_id=5)
    with pytest.raises(ValueError):
        resolve_claims(window, {1: ClaimWin(window_id=4, seat=1)})


def test_resolve_claims_rejects_duplicate_pung_kong_across_seats() -> None:
    """01-rules-spec.md §6 point 5: this can't happen in a real deal, so it's a hard
    programming error (mismatched fixtures) rather than a resolvable tie."""
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_PUNG,)),
            ClaimOffer(seat=2, can_win=False, melds=(_PUNG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {
        1: ClaimPung(window_id=1, seat=1, meld=_PUNG),
        2: ClaimPung(window_id=1, seat=2, meld=_PUNG),
    }
    with pytest.raises(AssertionError):
        resolve_claims(window, responses)


# --- can_close_early: doc-mandated scenarios (00-architecture.md §4) -------------------------


def test_close_early_true_once_all_responded() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=False, melds=(_CHOW,)),))
    responses: dict[int, ClaimResponse] = {1: Pass(window_id=1, seat=1)}
    assert can_close_early(window, responses)


def test_no_close_when_nothing_received_yet() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=False, melds=(_CHOW,)),))
    assert not can_close_early(window, {})


def test_no_close_when_pending_seat_could_still_pung_over_a_chow() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_CHOW,)),
            ClaimOffer(seat=2, can_win=False, melds=(_PUNG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {1: ClaimChow(window_id=1, seat=1, meld=_CHOW)}
    assert not can_close_early(window, responses)


def test_close_early_when_pending_seat_can_only_chow_and_pung_already_in_hand() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_CHOW,)),
            ClaimOffer(seat=2, can_win=False, melds=(_PUNG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {2: ClaimPung(window_id=1, seat=2, meld=_PUNG)}
    assert can_close_early(window, responses)


def test_no_close_when_pending_seat_could_still_kong_over_a_pung() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=2, can_win=False, melds=(_PUNG,)),
            ClaimOffer(seat=3, can_win=False, melds=(_KONG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {2: ClaimPung(window_id=1, seat=2, meld=_PUNG)}
    assert not can_close_early(window, responses)


def test_close_early_when_pending_seat_can_only_pung_and_kong_already_in_hand() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=2, can_win=False, melds=(_PUNG,)),
            ClaimOffer(seat=3, can_win=False, melds=(_KONG,)),
        ),
    )
    responses: dict[int, ClaimResponse] = {3: ClaimKong(window_id=1, seat=3, meld=_KONG)}
    assert can_close_early(window, responses)


def test_no_close_when_pending_win_seat_is_closer_to_discarder() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=True),
            ClaimOffer(seat=3, can_win=True),
        ),
    )
    responses: dict[int, ClaimResponse] = {3: ClaimWin(window_id=1, seat=3)}
    assert not can_close_early(window, responses)  # seat 1 is closer than seat 3


def test_close_early_when_pending_win_seat_is_farther_from_discarder() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=True),
            ClaimOffer(seat=3, can_win=True),
        ),
    )
    responses: dict[int, ClaimResponse] = {1: ClaimWin(window_id=1, seat=1)}
    assert can_close_early(window, responses)  # seat 3 can never beat seat 1's win


def test_no_close_when_a_pending_seat_could_still_win() -> None:
    window = _window(
        0,
        (
            ClaimOffer(seat=1, can_win=False, melds=(_PUNG,)),
            ClaimOffer(seat=2, can_win=True),
        ),
    )
    responses: dict[int, ClaimResponse] = {1: ClaimPung(window_id=1, seat=1, meld=_PUNG)}
    assert not can_close_early(window, responses)


def test_close_early_rejects_response_from_unoffered_seat() -> None:
    window = _window(0, (ClaimOffer(seat=1, can_win=True),))
    with pytest.raises(ValueError):
        can_close_early(window, {2: ClaimWin(window_id=1, seat=2)})


# --- can_close_early: hypothesis sweep, cross-checked against brute force --------------------


def _meld_for(kind: MeldKind, source_seat: int) -> Meld:
    if kind == MeldKind.CHOW:
        return Meld(MeldKind.CHOW, (_MAN_1[0], _MAN_2[0], _MAN_3[0]), from_seat=source_seat)
    if kind == MeldKind.PUNG:
        return Meld(MeldKind.PUNG, tuple(_MAN_4[:3]), from_seat=source_seat)
    return Meld(MeldKind.EXPOSED_KONG, tuple(_MAN_5), from_seat=source_seat)


def _all_options(offer: ClaimOffer, window: ClaimWindow) -> list[ClaimResponse]:
    options: list[ClaimResponse] = [Pass(window_id=window.window_id, seat=offer.seat)]
    if offer.can_win:
        options.append(ClaimWin(window_id=window.window_id, seat=offer.seat))
    for meld in offer.melds:
        if meld.kind == MeldKind.CHOW:
            options.append(ClaimChow(window_id=window.window_id, seat=offer.seat, meld=meld))
        elif meld.kind == MeldKind.PUNG:
            options.append(ClaimPung(window_id=window.window_id, seat=offer.seat, meld=meld))
        elif meld.kind == MeldKind.EXPOSED_KONG:
            options.append(ClaimKong(window_id=window.window_id, seat=offer.seat, meld=meld))
    return options


@st.composite
def _claim_scenarios(
    draw: st.DrawFn,
) -> tuple[ClaimWindow, dict[int, ClaimResponse], dict[int, ClaimOffer]]:
    """A realistic claim window: at most one seat holds pung/kong-tier eligibility and at
    most one seat (the discarder's next) holds chow eligibility -- the same structural
    constraints `melds.legal_claims` enforces -- plus an arbitrary subset of the other seats
    each independently eligible to win (01-rules-spec.md §6 point 4's multi-win case)."""
    source_seat = draw(st.integers(0, 3))
    chow_seat = (source_seat + 1) % 4
    other_seats = [s for s in range(4) if s != source_seat]

    chow_available = draw(st.booleans())
    pk_holder = draw(st.sampled_from([None, *other_seats]))
    pk_shape = draw(st.sampled_from(["pung", "kong", "both"]))
    win_seats = {s for s in other_seats if draw(st.booleans())}

    offers: dict[int, ClaimOffer] = {}
    for seat in other_seats:
        melds: list[Meld] = []
        if seat == pk_holder:
            if pk_shape in ("pung", "both"):
                melds.append(_meld_for(MeldKind.PUNG, source_seat))
            if pk_shape in ("kong", "both"):
                melds.append(_meld_for(MeldKind.EXPOSED_KONG, source_seat))
        if seat == chow_seat and chow_available:
            melds.append(_meld_for(MeldKind.CHOW, source_seat))
        can_win = seat in win_seats
        if can_win or melds:
            offers[seat] = ClaimOffer(seat=seat, can_win=can_win, melds=tuple(melds))

    assume(offers)

    window = _window(source_seat, tuple(offers.values()))

    eligible = list(offers.keys())
    responded = draw(st.sets(st.sampled_from(eligible)))
    responses: dict[int, ClaimResponse] = {
        seat: draw(st.sampled_from(_all_options(offers[seat], window))) for seat in responded
    }
    return window, responses, offers


@given(_claim_scenarios())
@settings(max_examples=300)
def test_can_close_early_matches_brute_force_outcome(
    scenario: tuple[ClaimWindow, dict[int, ClaimResponse], dict[int, ClaimOffer]],
) -> None:
    window, responses, offers = scenario
    pending = [s for s in offers if s not in responses]

    if not pending:
        assert can_close_early(window, responses)
        return

    def _identity(resolution: object) -> tuple[int | None, type | None]:
        result = resolution
        return (result.winning_seat, type(result.action) if result.action else None)  # type: ignore[attr-defined]

    baseline = _identity(resolve_claims(window, responses))
    option_lists = [_all_options(offers[seat], window) for seat in pending]

    outcome_could_change = False
    for combo in itertools.product(*option_lists):
        full = dict(responses)
        full.update(zip(pending, combo, strict=True))
        if _identity(resolve_claims(window, full)) != baseline:
            outcome_could_change = True
            break

    assert can_close_early(window, responses) == (not outcome_could_change)
