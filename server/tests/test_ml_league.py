"""`ml/league.py` and its PPO wiring: pool sampling and weights, snapshot cadence and cap,
persona rewards, `FROZEN` seats never trained on, checkpoint round trip and resume, stage C2,
and a CPU smoke run of `ml/configs/rl_league.yaml` (docs/ml.md §11)."""

from __future__ import annotations

import itertools
import json
from collections import Counter
from dataclasses import replace
from pathlib import Path

import pytest

np = pytest.importorskip("numpy")
torch = pytest.importorskip("torch")

from mahjong_core.presets import RULESET_PRESETS
from ml.curriculum import Curriculum
from ml.encode_v2 import N_POLICY_CHANNELS, N_POLICY_SCALARS, ruleset_features
from ml.league import (
    PAST,
    League,
    LeagueConfig,
    Persona,
    pairwise_points,
    pairwise_scores,
    persona_rewards,
)
from ml.policy_net import PolicyNet, PolicyNetConfig
from ml.ppo import (
    Collector,
    Encoder,
    Learner,
    PPOConfig,
    StageParams,
    ach_policy_loss,
    build_schedule,
    main_config,
    ppo_policy_loss,
    reward_divisors,
    train_ppo,
)
from ml.train_env import (
    FROZEN,
    LEARNER,
    PRESET_IDS,
    EnvConfig,
    SubprocVecTrainEnv,
    TrainEnv,
    VecTrainEnv,
    opponent_ids,
    unpack_rows,
)

_TINY = PolicyNetConfig(channels=8, blocks=1)
_CPU = torch.device("cpu")


def _league(**kw) -> League:
    return League(LeagueConfig(**kw), _TINY, _CPU, seed=0)


def _policy(seed: int) -> PolicyNet:
    torch.manual_seed(seed)
    return PolicyNet(_TINY)


def test_persona_rewards_scale_only_the_named_outcome():
    aggressive, defensive = Persona("a", win=1.3), Persona("d", deal_in=1.5)
    ron = np.array([3.0, -3.0, 0.0, 0.0], dtype=np.float32)
    ron_info = np.array([0, 1, 15, 0, 0])
    np.testing.assert_allclose(persona_rewards(ron, ron_info, aggressive), [3.9, -3.0, 0, 0])
    np.testing.assert_allclose(persona_rewards(ron, ron_info, defensive), [3.0, -4.5, 0, 0])
    tsumo = np.array([3.0, -1.0, -1.0, -1.0], dtype=np.float32)
    tsumo_info = np.array([0, -1, 15, 0, 0])
    np.testing.assert_allclose(persona_rewards(tsumo, tsumo_info, defensive), tsumo)
    np.testing.assert_allclose(persona_rewards(tsumo, tsumo_info, aggressive), [3.9, -1, -1, -1])
    draw = np.zeros(4, dtype=np.float32)
    draw_info = np.array([-1, -1, 15, 0, 0])
    for p in (aggressive, defensive):
        np.testing.assert_array_equal(persona_rewards(draw, draw_info, p), draw)
    assert persona_rewards(ron, ron_info, aggressive) is not ron


def test_pairwise_scores_are_half_at_parity():
    r = np.array([2.0, -2.0, 0.0, 0.0])
    assert pairwise_scores(r, [0], [1, 2, 3]) == 3.0
    assert pairwise_scores(r, [1], [0, 2, 3]) == 0.0
    assert pairwise_scores(r, [2], [0, 1, 3]) == 1.5
    # exchangeable seats: averaged over which seat is the learner, the share is 1/2
    shares = [pairwise_scores(r, [s], [o for o in range(4) if o != s]) / 3 for s in range(4)]
    assert np.mean(shares) == pytest.approx(0.5)


def test_pfsp_weights_favour_snapshots_the_learner_struggles_against():
    league = _league(pfsp_power=2.0)
    for i in range(3):
        league.add(PAST, _policy(i), decisions=i, updates=i)
    easy, even, hard = league.entries
    easy.score, easy.games = 90.0, 100.0
    hard.score, hard.games = 10.0, 100.0
    w = league.weights(league.entries)
    assert even.win_share == 0.5 and w.sum() == pytest.approx(1.0)
    raw = np.array([(1 - e.win_share) ** 2 for e in league.entries])
    np.testing.assert_allclose(w, raw / raw.sum())
    assert w[2] > w[1] > w[0]

    league.rotated_at = None
    draws = Counter()
    for u in range(400):
        league.rotate(u * league.cfg.rotate_every)
        draws.update(league.active)
    total = sum(draws.values())
    for e, p in zip(league.entries, w, strict=True):
        assert draws[e.id] / total == pytest.approx(p, abs=0.03)


def test_pairwise_points_sum_learner_minus_other_payments():
    r = np.array([2.0, -2.0, 0.5, -0.5])
    assert pairwise_points(r, [0], [1, 2, 3]) == pytest.approx(8.0)
    assert pairwise_points(r, [1, 2], [0, 3]) == pytest.approx(-4.0 - 1.5 + -1.5 + 1.0)
    # zero-sum and exchangeable: averaged over which seat is the learner, the mean is 0
    total = sum(pairwise_points(r, [s], [o for o in range(4) if o != s]) for s in range(4))
    assert total == pytest.approx(0.0)


def test_points_metric_weights_by_payment_not_win_frequency():
    league = _league(pfsp_metric="points", points_scale=0.5, stat_decay=1.0)
    for i in range(3):
        league.add(PAST, _policy(i), decisions=i, updates=i)
    big, even, small = league.entries
    # vs `big` the learner wins 1 hand in 4 but wins it big; vs `small` it wins often but cheap
    win_big = np.array([8.0, -8.0, 0.0, 0.0], dtype=np.float32)
    lose_small = np.array([-1.0, 1.0, 0.0, 0.0], dtype=np.float32)
    league.observe([(big.id, win_big, 0b0001)] + [(big.id, lose_small, 0b0001)] * 3)
    league.observe([(small.id, -win_big, 0b0001)] + [(small.id, -lose_small, 0b0001)] * 3)
    assert big.win_share < 0.5 < small.win_share  # x calls the learner weaker against `big`
    assert big.points_diff > 0 > small.points_diff  # the points say the opposite
    assert big.pairs == big.games == 12 and even.pairs == 0
    assert big.points_diff == pytest.approx(big.points / 13)
    assert league.share(even) == 0.5
    assert league.share(big) == pytest.approx(1 / (1 + np.exp(-big.points_diff / 0.5)))
    w = league.weights(league.entries)
    raw = np.array([(1 - league.share(e)) ** 2 for e in league.entries])
    np.testing.assert_allclose(w, raw / raw.sum())
    assert w[2] > w[1] > w[0]
    # the win metric on the same counts ranks them the other way
    league.cfg.pfsp_metric = "win"
    w_win = league.weights(league.entries)
    assert w_win[0] > w_win[1] > w_win[2]


def test_points_metric_elo_and_metrics():
    league = _league(pfsp_metric="points", stat_decay=1.0)
    a = league.add(PAST, _policy(0), 0, 0)
    p = league.add("aggressive", _policy(1), 0, 0)
    up = np.array([1.0, -1.0, 0.0, 0.0], dtype=np.float32)
    league.observe([(a.id, up, 0b0001)] * 20 + [(p.id, -up, 0b0001)] * 5)
    assert league.elo > a.elo + 50
    m = league.metrics()
    vs = m["league_vs"][f"past{a.id}"]
    assert vs["pts"] == pytest.approx(a.points_diff, abs=1e-4) and vs["p"] > 0.5
    assert m["league_pts_past"] == pytest.approx(80 / 60, abs=1e-4)  # per pair, no prior
    assert m["league_pts_persona"] == pytest.approx(-20 / 15, abs=1e-4)
    json.dumps(m)
    with pytest.raises(ValueError, match="pfsp_metric"):
        LeagueConfig(pfsp_metric="elo")
    with pytest.raises(ValueError, match="points_scale"):
        LeagueConfig(points_scale=0.0)


def test_old_state_without_points_stats_loads_at_the_prior():
    league = _league(stat_decay=1.0)
    for i in range(2):
        league.add(PAST if i == 0 else "defensive", _policy(i), i * 10, i)
    league.observe([(1, np.array([1.0, -1.0, 0.0, 0.0], dtype=np.float32), 0b0001)] * 4)
    league.rotate(5)
    old = league.state_dict()
    for e in old["entries"]:
        del e["points"], e["pairs"]  # the pre-points format
    resumed = _league(pfsp_metric="points", stat_decay=1.0)
    resumed.load_state_dict(old)
    a = resumed.entries[0]
    assert (a.score, a.games, a.hands, a.wins) == (12.0, 12.0, 4.0, 4.0)
    assert (a.points, a.pairs, a.points_diff) == (0.0, 0.0, 0.0)
    assert resumed.share(a) == 0.5 and resumed.metrics()["league_vs"]["past1"]["x"] > 0.5
    np.testing.assert_allclose(resumed.weights(resumed.entries), [0.5, 0.5])
    assert resumed.fit_elo() == resumed.elo  # no points evidence yet: Elo holds
    resumed.observe([(1, np.array([1.0, -1.0, 0.0, 0.0], dtype=np.float32), 0b0001)])
    assert a.pairs == 3 and a.points == pytest.approx(4.0) and resumed.share(a) > 0.5
    assert resumed.elo > a.elo
    assert "points" in resumed.state_dict()["entries"][0]


def test_mix_shares_and_empty_pools_fall_back_to_self_play():
    league = _league(active_past=3, active_personas=1)
    league.rotate(0)
    assert league.mix() == ((1.0, 4, 0),)
    league.add(PAST, _policy(0), 0, 0)
    league.rotate(0)
    assert league.mix() == ((0.65, 4, 0), (pytest.approx(0.35), 1, 1))
    league.add("aggressive", _policy(1), 0, 0)
    league.add(PAST, _policy(2), 0, 0)
    league.rotate(0)
    mix = league.mix()
    assert mix[0] == (0.5, 4, 0)
    shares = {oid: w for w, _, oid in mix[1:]}
    assert sum(shares[i] for i in (1, 3) if i in shares) == pytest.approx(0.35)
    assert shares[2] == pytest.approx(0.15)
    assert len(league.active) == 4
    assert all(learners == 1 for _, learners, oid in mix if oid)
    EnvConfig(mix=mix)  # a valid env table


def test_rotation_cadence():
    league = _league(rotate_every=4)
    league.add(PAST, _policy(0), 0, 0)
    assert league.rotate(10)
    assert not league.rotate(11) and not league.rotate(13)
    assert league.rotate(14)
    league.add(PAST, _policy(1), 0, 15)
    assert league.rotate(15)  # a new snapshot redraws at once


def test_snapshot_cadence_and_caps():
    league = _league(snapshot_every=100, max_past=3, max_personas=2)
    assert league.snapshot_due(0)
    taken = []
    for decisions in range(0, 1000, 7):
        if league.snapshot_due(decisions):
            league.begin_snapshot(decisions, updates=decisions)
            taken.append(league.add(PAST, _policy(decisions), decisions, decisions).id)
            league.add("aggressive", _policy(decisions + 1), decisions, decisions)
    starts = [e.decisions for e in league.by_kind(True)]
    assert len(taken) == 10
    assert len(league.by_kind(True)) == 3 and len(league.by_kind(False)) == 2
    assert [e.id for e in league.by_kind(True)] == taken[-3:]
    assert all(b - a >= 100 for a, b in itertools.pairwise(starts))
    # the snapshot is a copy: later learner updates don't reach it
    p = _policy(5)
    e = league.add(PAST, p, 2000, 2000)
    with torch.no_grad():
        next(p.parameters()).add_(1.0)
    for name, v in league.model(e.id).state_dict().items():
        torch.testing.assert_close(v, e.state[name])


def test_defaults_match_the_plan():
    c = LeagueConfig()
    assert (c.self_share, c.past_share, c.persona_share) == (0.5, 0.35, 0.15)
    assert (c.snapshot_every, c.max_past) == (50_000_000, 32)
    assert {(p.name, p.win, p.deal_in) for p in c.personas} == {
        ("aggressive", 1.3, 1.0),
        ("defensive", 1.0, 1.5),
    }


def test_evicted_snapshot_stays_playable_while_its_hands_finish():
    league = _league(max_past=1)
    first = league.add(PAST, _policy(0), 0, 0).id
    league.add(PAST, _policy(1), 1, 1)
    assert league.entry(first) is None and league.model(first) is not None
    assert league.kind(first) == PAST
    league.begin_snapshot(10, updates=1000)
    with pytest.raises(KeyError):
        league.model(first)


def test_observe_counts_win_share_and_elo():
    league = _league(stat_decay=1.0)
    a = league.add(PAST, _policy(0), 0, 0)
    b = league.add("defensive", _policy(1), 0, 0)
    win = np.array([3.0, -1.0, -1.0, -1.0], dtype=np.float32)
    lose = np.array([-3.0, 3.0, 0.0, 0.0], dtype=np.float32)
    draw = np.zeros(4, dtype=np.float32)
    hands = [(a.id, win, 0b0001)] * 30 + [(a.id, lose, 0b0001)] * 10 + [(b.id, draw, 0b0010)]
    hands += [(0, win, 0b1111)] * 9
    m = league.observe(hands)
    assert a.hands == 40 and a.wins == 30 and a.games == 120
    assert a.score == 30 * 3  # a loss pays seat 1 and leaves the learner below the zero seats
    assert a.win_share > 0.5 and b.win_share == 0.5
    assert m["league_mix_self"] == pytest.approx(9 / 50)
    assert m["league_mix_past"] == pytest.approx(40 / 50)
    assert m["league_draw_persona"] == 1.0 and m["league_draw_self"] == 0.0
    assert league.elo > a.elo + 100  # anchored at 0 when taken, the learner beats it
    c = league.add(PAST, _policy(2), 1, 1)
    assert c.elo == league.elo
    metrics = league.metrics()
    assert metrics["league_past"] == 2 and metrics["league_personas"] == 1
    assert metrics["league_vs"][f"past{a.id}"]["win"] == 0.75
    json.dumps(metrics)


def test_state_dict_round_trip():
    league = _league()
    for i in range(3):
        league.add(PAST if i != 1 else "aggressive", _policy(i), i * 10, i)
    league.observe([(1, np.array([1.0, -1.0, 0.0, 0.0]), 1)])
    league.rotate(5)
    league.begin_snapshot(30, 5)
    other = _league()
    other.load_state_dict(league.state_dict())
    assert [(e.id, e.kind, e.decisions, e.score) for e in other.entries] == [
        (e.id, e.kind, e.decisions, e.score) for e in league.entries
    ]
    assert (other.next_id, other.next_snapshot, other.elo, other.active) == (
        league.next_id,
        league.next_snapshot,
        league.elo,
        league.active,
    )
    x = torch.randn(2, N_POLICY_CHANNELS, 34), torch.randn(2, N_POLICY_SCALARS)
    for e in league.entries:
        torch.testing.assert_close(
            other.model(e.id)(*x, aux=False).logits, league.model(e.id)(*x, aux=False).logits
        )
    assert league.rotate(100) and other.rotate(100)
    assert league.active == other.active


def test_env_mix_seats_and_opponent_id_on_every_row():
    mix = ((0.5, 4, 0), (0.3, 1, 7), (0.2, 2, 300))
    env = TrainEnv(EnvConfig(mix=mix))
    rng = np.random.default_rng(0)
    seen = Counter()
    for seed in range(60):
        env.reset(seed)
        learners = sum(r == LEARNER for r in env.roles)
        frozen = sum(r == FROZEN for r in env.roles)
        assert learners + frozen == 4
        assert {4: 0, 1: 7, 2: 300}[learners] == env.opponent_id
        seen[env.opponent_id] += 1
        for _ in range(5):
            u = unpack_rows(env.row[None])
            assert opponent_ids(u)[0] == env.opponent_id
            assert u["role"][0] == env.roles[env.seat]
            if env.step(int(rng.choice(np.flatnonzero(env.mask))))[0]:
                break
    assert set(seen) == {0, 7, 300}


def test_env_alt_rulesets_play_the_preset_and_tag_rows():
    env = TrainEnv(EnvConfig(alt_rulesets=(("hk_casual", 0.25), ("hk_strict", 0.25))))
    counts = Counter()
    for seed in range(200):
        env.reset(seed)
        u = unpack_rows(env.row[None], ("ruleset", "min_faan"))
        rid = int(u["ruleset"][0])
        name = "base" if rid == 0 else PRESET_IDS[rid - 1]
        counts[name] += 1
        expected = env.cfg.ruleset if rid == 0 else RULESET_PRESETS[name]
        assert env.env.state.ruleset == expected
        assert int(u["min_faan"][0]) == expected.min_faan
    assert counts["hk_casual"] > 25 and counts["hk_strict"] > 25 and counts["base"] > 70
    enc = Encoder(RULESET_PRESETS["hk_classic"])
    vec = enc._ruleset(np.array([5, 3, 1], dtype=np.uint8), np.array([3, 0, 2], dtype=np.uint8))
    np.testing.assert_array_equal(vec[0], ruleset_features(RULESET_PRESETS["hk_strict"]))
    np.testing.assert_array_equal(vec[1], ruleset_features(RULESET_PRESETS["hk_classic"]))
    np.testing.assert_array_equal(vec[2], ruleset_features(RULESET_PRESETS["hk_casual"]))


def test_subprocess_env_carries_the_mix():
    cfg = EnvConfig(mix=((0.5, 4, 0), (0.5, 1, 9)), alt_rulesets=(("hk_strict", 0.5),))
    a = VecTrainEnv(4, 3, cfg)
    with SubprocVecTrainEnv(4, 3, cfg, n_workers=2) as b:
        ba, bb = a.reset(), b.reset()
        np.testing.assert_array_equal(ba.rows, bb.rows)


class _RecordingLeague(League):
    def __init__(self) -> None:
        super().__init__(LeagueConfig(), _TINY, _CPU, seed=0)
        self.calls: Counter[int] = Counter()

    def model(self, oid: int) -> PolicyNet:
        self.calls[oid] += 1
        return super().model(oid)


def test_frozen_seats_act_with_their_snapshot_and_never_produce_samples():
    league = _RecordingLeague()
    snap = league.add(PAST, _policy(1), 0, 0)
    mix = ((0.4, 4, 0), (0.6, 1, snap.id))
    venv = VecTrainEnv(4, 11, EnvConfig(mix=mix))
    learner = Learner(PPOConfig(channels=8, blocks=1, device="cpu"), _policy(2))
    collector = Collector(venv, 0, np.random.default_rng(0), league)
    params = StageParams(learners=4, keep_prob=0.0, oracle_k=0, league=True)
    episodes, stats, _ = collector.collect(learner, params, 120)
    assert league.calls[snap.id] > 0
    vs_snapshot = [e for e in episodes if e.opponent == snap.id]
    assert vs_snapshot and any(e.opponent == 0 for e in episodes)
    for e in episodes:
        u = unpack_rows(e.rows, ("role", "opponent"))
        assert (u["role"] == LEARNER).all()
        assert (opponent_ids(u) == e.opponent).all()
        learner_seats = {s for s in range(4) if int(e.info[2]) >> s & 1}
        assert set(e.seats.tolist()) <= learner_seats
        assert len(learner_seats) == (4 if e.opponent == 0 else 1)
    assert len(stats) == sum(
        len({s for s in range(4) if int(e.info[2]) >> s & 1}) for e in episodes
    )


def test_c2_runs_with_a_league_and_stays_a_stub_without():
    stub = Curriculum.from_config({"start": "C2"})
    assert stub.complete()
    with pytest.raises(NotImplementedError, match="league"):
        stub.params(0)
    cur = Curriculum.from_config({"start": "C2", "window": 10}, league=True)
    assert not cur.complete()
    p = cur.params(0)
    assert (p.league, p.learners, p.min_faan, p.oracle_k, p.keep_prob, p.beta) == (
        True,
        4,
        3,
        0,
        0.0,
        0.0,
    )
    assert dict(p.alt_rulesets) == {"hk_casual": 0.1, "hk_strict": 0.1}
    cur.advance(0)
    cur.observe([])
    assert cur.advance(10**12) is None and not cur.complete()  # the last stage never advances


def test_hold_final_advances_into_c2_once_the_league_exists():
    stage = {"name": "C1", "anneal_decisions": 0, "win_rate": 0.0, "sub_min_tenpai_max": None}
    raw = {"start": "C1", "window": 1, "stages": [stage], "hold_final": True}
    from ml.ppo import HandStat

    hand = HandStat(False, False, False, True, False, False, 0.0, 3)
    for league, expect in ((False, None), (True, "C2")):
        cur = Curriculum.from_config(raw, league=league)
        cur.advance(0)
        cur.observe([hand])
        assert cur.advance(1) == expect
        assert (cur.held_at is not None) == (not league)


def test_ach_loss_matches_its_definition_and_clips():
    torch.manual_seed(0)
    logits = torch.randn(4, 109, requires_grad=True)
    mask = torch.zeros(4, 109, dtype=torch.bool)
    mask[:, :5] = True
    actions = torch.tensor([0, 1, 2, 3])
    old = torch.log_softmax(logits.detach()[:, :5], 1).gather(1, actions[:, None]).squeeze(1)
    adv = torch.tensor([1.0, -1.0, 2.0, 0.5])
    out = ach_policy_loss(logits, mask, actions, old, adv, 0.2, 6.0, 1.0)
    y = logits[:, :5] - logits[:, :5].mean(1, keepdim=True)
    want = -(y.gather(1, actions[:, None]).squeeze(1) / old.exp() * adv).mean()
    torch.testing.assert_close(out["pg"], want)
    out["pg"].backward()
    assert (logits.grad[:, 5:] == 0).all()
    assert logits.grad[0, 0] < 0 and logits.grad[1, 1] > 0  # descent raises / lowers y(a)
    ppo = ppo_policy_loss(logits.detach(), mask, actions, old, adv, 0.2)
    assert out["entropy"].item() == pytest.approx(ppo["entropy"].item())
    # a logit past the threshold in the advantage's direction gets no gradient
    big = torch.zeros(1, 109, requires_grad=True)
    with torch.no_grad():
        big[0, 0] = 10.0
    out = ach_policy_loss(big, mask[:1], actions[:1], torch.tensor([-0.01]), adv[:1], 0.2, 6.0, 1.0)
    out["pg"].backward()
    assert (big.grad == 0).all() and out["clip_frac"] == 1.0


def _tiny(tmp_path: Path, name: str, **kw) -> PPOConfig:
    base = {
        "out": str(tmp_path / name),
        "envs": 4,
        "workers": 0,
        "batch_size": 64,
        "minibatch": 32,
        "aux_rate": 0.2,
        "save_every": 1,
        "device": "cpu",
        "channels": 8,
        "blocks": 1,
    }
    return PPOConfig(**{**base, **kw})


def _records(out: Path) -> list[dict]:
    return [json.loads(x) for x in (out / "metrics.jsonl").read_text().splitlines()]


_LEAGUE = {
    "snapshot_every": 150,
    "persona_updates": 1,
    "active_past": 2,
    "rotate_every": 2,
    "personas": [{"name": "aggressive", "win": 1.3}, {"name": "defensive", "deal_in": 1.5}],
}


@pytest.fixture(scope="module")
def c1_ckpt(tmp_path_factory) -> Path:
    tmp = tmp_path_factory.mktemp("c1")
    stage = {"min_faan": 3, "learners": 4, "keep_prob": 0.0, "oracle_k": 0, "beta": 0.0}
    out = train_ppo(_tiny(tmp, "c1", stage=stage), max_updates=1)
    return out / "ckpt_last.pt"


def test_league_run_snapshots_trains_personas_and_resumes(tmp_path, c1_ckpt):
    cfg = _tiny(
        tmp_path,
        "league",
        init_ckpt=str(c1_ckpt),
        aux_coef_start=0.05,
        curriculum={"start": "C2", "window": 50},
        league=_LEAGUE,
    )
    # a tiny run's hands take ~100 env steps: past/persona hands finish from about update 7
    out = train_ppo(cfg, max_updates=10)
    lines = _records(out)
    assert [r["update"] for r in lines] == list(range(1, 11))
    assert all(r["stage"] == "C2" and r["min_faan"] == 3 for r in lines)
    first = lines[0]
    assert first["league_snapshot"] == 1 and first["league_personas"] == 2
    assert first["aux_coef"] == pytest.approx(0.05)
    snaps = [r["league_snapshot"] for r in lines if "league_snapshot" in r]
    assert len(snaps) >= 2 and lines[-1]["league_past"] == len(snaps)
    assert all("league_elo" in r and "league_mix_self" in r for r in lines)
    assert any(r["league_mix_past"] + r["league_mix_persona"] > 0 for r in lines[1:])
    assert "batch_draw_rate" in lines[-1]

    init = torch.load(c1_ckpt, weights_only=False, map_location="cpu")
    ckpt = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")
    first_snap = ckpt["league"]["entries"][0]
    assert first_snap["kind"] == PAST and first_snap["decisions"] == 0
    for k, v in init["learner"]["policy"].items():
        torch.testing.assert_close(first_snap["state"][k], v)
    critic = init["learner"]["critic"]
    persona = next(e for e in ckpt["league"]["entries"] if e["kind"] == "aggressive")
    assert any(
        not torch.equal(persona["state"][k], v) for k, v in init["learner"]["policy"].items()
    )

    train_ppo(cfg, resume=True, max_updates=1)
    lines2 = _records(out)
    assert lines2[-1]["update"] == 11
    resumed = torch.load(out / "ckpt_last.pt", weights_only=False, map_location="cpu")

    def past(c):
        return [e["id"] for e in c["league"]["entries"] if e["kind"] == PAST]

    assert past(resumed)[: len(past(ckpt))] == past(ckpt)  # under max_past nothing is evicted
    assert resumed["league"]["next_id"] >= ckpt["league"]["next_id"]
    assert critic.keys() == resumed["learner"]["critic"].keys()


def test_league_run_from_init_ckpt_starts_from_its_learner(tmp_path, c1_ckpt):
    cfg = _tiny(
        tmp_path,
        "init",
        init_ckpt=str(c1_ckpt),
        lr=1e-4,
        curriculum={"start": "C2"},
        league={**_LEAGUE, "persona_share": 0.0},
    )
    train_ppo(cfg, max_updates=0)
    ckpt = torch.load(Path(cfg.out) / "ckpt_last.pt", weights_only=False, map_location="cpu")
    init = torch.load(c1_ckpt, weights_only=False, map_location="cpu")
    for part in ("policy", "critic", "adapter", "popart"):
        for k, v in init["learner"][part].items():
            torch.testing.assert_close(ckpt["learner"][part][k], v)
    groups = ckpt["learner"]["opt"]["param_groups"]
    assert groups[0]["lr"] == 1e-4 and ckpt["learner"]["opt"]["state"]
    train_ppo(replace(cfg, out=str(tmp_path / "init2")), max_updates=1)
    ckpt = torch.load(tmp_path / "init2" / "ckpt_last.pt", weights_only=False, map_location="cpu")
    assert [e["kind"] for e in ckpt["league"]["entries"]] == [PAST]  # persona_share 0: none


def test_league_config_without_league_stage_changes_nothing(tmp_path):
    stage = {"min_faan": 0, "learners": 1, "keep_prob": 0.5, "oracle_k": 5, "beta": 1.0}

    def run(name, **kw):
        out = train_ppo(_tiny(tmp_path, name, stage=stage, **kw), max_updates=1)
        rec = _records(out)[0]
        return {k: v for k, v in rec.items() if not k.endswith("_s") and "per_s" not in k}

    assert run("a") == run("b", league={})


def test_league_stage_without_a_league_block_refuses(tmp_path):
    stage = {"min_faan": 3, "learners": 4, "keep_prob": 0.0, "oracle_k": 0, "league": True}
    with pytest.raises(ValueError, match="league"):
        train_ppo(_tiny(tmp_path, "x", stage=stage), max_updates=1)


def test_ach_switch_trains(tmp_path):
    stage = {"min_faan": 0, "learners": 4, "keep_prob": 0.0, "oracle_k": 0, "beta": 0.5}
    out = train_ppo(_tiny(tmp_path, "ach", stage=stage, policy_loss="ach"), max_updates=2)
    lines = _records(out)
    assert len(lines) == 2 and all(np.isfinite(r["pg"]) for r in lines)
    with pytest.raises(ValueError, match="policy_loss"):
        from ml.ppo import load_ppo_config

        load_ppo_config({"policy_loss": "nope"})


def test_league_config_file_smoke(tmp_path, c1_ckpt):
    cfg = main_config(Path("ml/configs/rl_league.yaml"))
    assert cfg.league is not None and cfg.init_ckpt.endswith("ckpt_last.pt")
    assert cfg.curriculum["start"] == "C2"
    p = build_schedule(cfg).params(0)
    assert p.league and p.min_faan == 3 and p.keep_prob == 0.0 and p.beta == 0.0
    smoke = replace(
        cfg,
        out=str(tmp_path / "smoke"),
        init_ckpt=str(c1_ckpt),
        device="cpu",
        envs=4,
        workers=2,
        batch_size=64,
        minibatch=32,
        league={**cfg.league, **_LEAGUE},
    )
    out = train_ppo(smoke, max_updates=3)
    lines = _records(out)
    assert len(lines) == 3 and lines[0]["league_snapshot"] == 1
    assert all(np.isfinite(r["pg"]) for r in lines)
    assert all("pts" in v and "x" in v for r in lines for v in r["league_vs"].values())

    # the live run's case: a checkpoint from before points stats resumes under this config
    path = out / "ckpt_last.pt"
    ckpt = torch.load(path, weights_only=False, map_location="cpu")
    for e in ckpt["league"]["entries"]:
        del e["points"], e["pairs"]
    torch.save(ckpt, path)
    train_ppo(smoke, resume=True, max_updates=1)
    last = _records(out)[-1]
    assert last["update"] == 4 and np.isfinite(last["league_elo"])
    resumed = torch.load(path, weights_only=False, map_location="cpu")
    assert all("pairs" in e for e in resumed["league"]["entries"])


def test_league_config_reward_scale_and_pfsp_metric():
    cfg = main_config(Path("ml/configs/rl_league.yaml"))
    div = reward_divisors(cfg)
    assert cfg.ruleset == "hk_classic" and div[0] == 1.0
    assert div[1 + PRESET_IDS.index("hk_classic")] == 1.0
    assert div[1 + PRESET_IDS.index("hk_casual")] == pytest.approx(3.6 / 0.87, abs=0.01)
    assert div[1 + PRESET_IDS.index("hk_strict")] == pytest.approx(0.98 / 0.87, abs=0.01)
    league = LeagueConfig.from_dict(cfg.league)
    assert league.pfsp_metric == "points" and league.points_scale == pytest.approx(0.83)
    assert league.persona_updates == 400
    assert {(p.name, p.win, p.deal_in) for p in league.personas} == {
        ("aggressive", 1.6, 1.0),
        ("defensive", 1.0, 2.0),
    }
    # every config other than the league's leaves rewards unscaled
    for path in Path("ml/configs").glob("rl_ppo_*.yaml"):
        assert set(reward_divisors(main_config(path))) == {1.0}
