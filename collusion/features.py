"""Behaviour features per (run, driver) from the runner's logs (ml-design v5 §7.3, card D2).

Only behaviour goes in: no price levels (bid / base_price, markup, absolute prices) and nothing
from the hidden roles. The function reads the action log and five columns of deals_out.csv; it
never sees the labels file.

Conventions (the §7.3 table leaves them open):
- A driver "appears" in a deal when it has a PRESENT row there.
- Bids (BID_PLACE, BID_UPDATE) and withdrawals count only when Redis accepted them (accepted = 1).
  ACCEPT_OFFER counts every attempt: losing the race to another driver is the same behaviour.
- A ratio whose denominator is 0 is 0. concession_interval_mean is 180 when there is no pair of
  consecutive bids.
- entry_delay_std is the population standard deviation (ddof = 0).
- Pair features use pairs of drivers that appeared together in at least MIN_TOGETHER deals of a
  run; a driver without such a partner gets 0 for every pair feature and n_partners = 0.
"""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from itertools import combinations

import numpy as np

FEATURES = [
    "participation_rate", "withdraw_rate", "late_withdraw_rate", "update_rate", "concession_interval_mean",
    "relative_step_mean", "entry_delay_mean", "entry_delay_std", "entry_after_first_other_mean", "win_rate",
    "offer_accept_rate", "no_concession_share", "sync_entry_max", "sync_entry_mean", "tie_rate_max",
    "tie_rate_mean", "no_undercut_max", "no_undercut_mean", "alternation_max", "alternation_mean",
    "cowithdraw_max", "cowithdraw_mean", "n_partners",
]

# The only deals_out.csv columns this module reads.
DEAL_COLUMNS = ("run_id", "deal_id", "base_price", "duration_sec", "winner_id")

MIN_TOGETHER = 5
LATE_WINDOW_S = 30.0
AFTER_OFFER_S = 10.0
SYNC_S = 3.0
TIE_SHARE = 0.005
NO_INTERVAL_S = 180.0

BIDS = ("BID_PLACE", "BID_UPDATE")


@dataclass
class _InDeal:
    """One driver's actions in one deal, in log order."""

    bids: list[tuple[float, float, str]] = field(default_factory=list)  # (t, price, action), accepted only
    withdraws: list[float] = field(default_factory=list)  # accepted only
    offers_seen: list[float] = field(default_factory=list)
    offer_accepts: int = 0


@dataclass
class _Deal:
    present: list[str] = field(default_factory=list)
    drivers: dict[str, _InDeal] = field(default_factory=lambda: defaultdict(_InDeal))
    # accepted bids and withdrawals of every driver, in log order: (driver, action, price)
    sequence: list[tuple[str, str, float | None]] = field(default_factory=list)


def _read_deals(deals_csv: str) -> dict[tuple[str, str], tuple[float, float, str]]:
    """(run_id, deal_id) -> (base_price, duration_sec, winner_id) from the five allowed columns."""
    out: dict[tuple[str, str], tuple[float, float, str]] = {}
    with open(deals_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        idx = [header.index(c) for c in DEAL_COLUMNS]
        for row in reader:
            run, deal, base, duration, winner = (row[i] for i in idx)
            key = (run, deal)
            if key in out:
                raise ValueError(f"deal {deal} appears twice in run {run}")
            out[key] = (float(base), float(duration), winner)
    return out


def _read_actions(actions_csv: str) -> dict[str, dict[str, _Deal]]:
    """run_id -> deal_id -> _Deal, from the DRIVER rows only."""
    runs: dict[str, dict[str, _Deal]] = defaultdict(dict)
    with open(actions_csv, newline="", encoding="utf-8") as f:
        reader = csv.reader(f)
        header = next(reader)
        c = {name: header.index(name) for name in
             ("run_id", "deal_id", "t_sec", "actor_type", "driver_id", "action", "price", "accepted")}
        for row in reader:
            if row[c["actor_type"]] != "DRIVER":
                continue
            run, deal_id, driver, action = row[c["run_id"]], row[c["deal_id"]], row[c["driver_id"]], row[c["action"]]
            deal = runs[run].get(deal_id)
            if deal is None:
                deal = runs[run][deal_id] = _Deal()
            t = float(row[c["t_sec"]])
            accepted = row[c["accepted"]] == "1"
            if action == "PRESENT":
                deal.present.append(driver)
                continue
            mine = deal.drivers[driver]
            if action in BIDS:
                if accepted:
                    price = float(row[c["price"]])
                    mine.bids.append((t, price, action))
                    deal.sequence.append((driver, action, price))
            elif action == "WITHDRAW":
                if accepted:
                    mine.withdraws.append(t)
                    deal.sequence.append((driver, action, None))
            elif action == "OFFER_SEEN":
                mine.offers_seen.append(t)
            elif action == "ACCEPT_OFFER":
                mine.offer_accepts += 1
    return runs


def _ratio(num: float, den: float) -> float:
    return num / den if den else 0.0


def _undercuts(sequence: list[tuple[str, str, float | None]], a: str, b: str) -> bool:
    """True when a or b ever bid below the other's live bid in this deal."""
    live: dict[str, float] = {}
    for driver, action, price in sequence:
        if driver not in (a, b):
            continue
        if action == "WITHDRAW":
            live.pop(driver, None)
            continue
        other = b if driver == a else a
        if other in live and price < live[other]:
            return True
        live[driver] = price
    return False


def _individual(deals: list[tuple[_Deal, float, str]], driver: str) -> list[float]:
    """The 12 individual features of one driver over the deals it appeared in."""
    appeared = bid_deals = places = updates = withdraws = late = 0
    seen = accepts = wins = no_concession = 0
    intervals: list[float] = []
    steps: list[float] = []
    entries: list[float] = []
    after_other: list[float] = []
    for deal, duration, winner in deals:
        appeared += 1
        mine = deal.drivers.get(driver, _InDeal())
        seen += len(mine.offers_seen)
        accepts += mine.offer_accepts
        for t in mine.withdraws:
            withdraws += 1
            if t >= duration - LATE_WINDOW_S or any(0 <= t - o <= AFTER_OFFER_S for o in mine.offers_seen):
                late += 1
        if not mine.bids:
            continue
        bid_deals += 1
        first_t, first_price = mine.bids[0][0], mine.bids[0][1]
        entries.append(first_t)
        others = [d.bids[0][0] for k, d in deal.drivers.items() if k != driver and d.bids]
        if others:
            after_other.append(first_t - min(others))
        updated = False
        for (t0, p0, _), (t1, p1, action) in zip(mine.bids, mine.bids[1:]):
            intervals.append(t1 - t0)
            if action == "BID_UPDATE":
                steps.append(_ratio(p0 - p1, first_price))
        for _, _, action in mine.bids:
            if action == "BID_PLACE":
                places += 1
            else:
                updates += 1
                updated = True
        if not updated:
            no_concession += 1
        if winner == driver:
            wins += 1
    return [
        _ratio(bid_deals, appeared),
        _ratio(withdraws, places + updates),
        _ratio(late, places + updates),
        _ratio(updates, places),
        float(np.mean(intervals)) if intervals else NO_INTERVAL_S,
        float(np.mean(steps)) if steps else 0.0,
        float(np.mean(entries)) if entries else 0.0,
        float(np.std(entries)) if entries else 0.0,
        float(np.mean(after_other)) if after_other else 0.0,
        _ratio(wins, bid_deals),
        _ratio(accepts, seen),
        _ratio(no_concession, bid_deals),
    ]


def _pair(deals: list[tuple[_Deal, float, str, float]], a: str, b: str) -> tuple[float, float, float, float, float]:
    """(sync_entry, tie_rate, no_undercut, alternation, cowithdraw) of drivers a and b."""
    both = sync = tie = clean = cowithdraw = wins_a = wins_b = 0
    for deal, _, winner, base in deals:
        da, db = deal.drivers.get(a), deal.drivers.get(b)
        if winner == a:
            wins_a += 1
        elif winner == b:
            wins_b += 1
        if da is not None and db is not None and da.withdraws and db.withdraws:
            cowithdraw += 1
        if da is None or db is None or not da.bids or not db.bids:
            continue
        both += 1
        if abs(da.bids[0][0] - db.bids[0][0]) <= SYNC_S:
            sync += 1
        if abs(da.bids[-1][1] - db.bids[-1][1]) < TIE_SHARE * base:
            tie += 1
        if not _undercuts(deal.sequence, a, b):
            clean += 1
    alternation = 1 - abs(wins_a - wins_b) / (wins_a + wins_b) if wins_a + wins_b else 0.0
    return _ratio(sync, both), _ratio(tie, both), _ratio(clean, both), alternation, _ratio(cowithdraw, len(deals))


def build_features(actions_csv: str, deals_csv: str) -> tuple[list[tuple[str, str]], np.ndarray]:
    """Features per (run_id, driver_id) for every driver that appeared in a run.

    Returns the keys sorted by (run_id, driver_id) and a matrix with one row per key and one
    column per name in FEATURES.
    """
    deal_info = _read_deals(deals_csv)
    runs = _read_actions(actions_csv)
    keys: list[tuple[str, str]] = []
    rows: list[list[float]] = []
    for run in sorted(runs):
        by_driver: dict[str, list[tuple[_Deal, float, str]]] = defaultdict(list)
        by_pair: dict[tuple[str, str], list[tuple[_Deal, float, str, float]]] = defaultdict(list)
        for deal_id, deal in runs[run].items():
            if (run, deal_id) not in deal_info:
                raise ValueError(f"deal {deal_id} of run {run} is missing from {deals_csv}")
            base, duration, winner = deal_info[(run, deal_id)]
            for d in deal.present:
                by_driver[d].append((deal, duration, winner))
            for a, b in combinations(sorted(set(deal.present)), 2):
                by_pair[(a, b)].append((deal, duration, winner, base))

        pair_values: dict[str, list[tuple[float, ...]]] = defaultdict(list)
        for (a, b), together in by_pair.items():
            if len(together) < MIN_TOGETHER:
                continue
            v = _pair(together, a, b)
            pair_values[a].append(v)
            pair_values[b].append(v)

        for driver in sorted(by_driver):
            row = _individual(by_driver[driver], driver)
            partners = pair_values.get(driver, [])
            for k in range(5):
                col = [v[k] for v in partners]
                row += [max(col), float(np.mean(col))] if col else [0.0, 0.0]
            row.append(float(len(partners)))
            keys.append((run, driver))
            rows.append(row)
    X = np.asarray(rows, dtype=float).reshape(len(rows), len(FEATURES))
    return keys, X
