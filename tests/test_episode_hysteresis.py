"""EpisodeAggregator: ENTER on first, bump on subsequent, EXIT after hysteresis gap."""
import pytest

from app.pipeline import aggregator as agg_mod
from app.pipeline.aggregator import EpisodeAggregator


class _StubIds:
    def __init__(self):
        self.next_id = 100
        self.bumps: list[tuple[int, float, float]] = []
        self.closed: list[tuple[int, float]] = []
        self.snap: dict[int, str] = {}

    def create(self, camera_id, zone_id, class_name, start_ts, max_confidence, snapshot_path):
        i = self.next_id
        self.next_id += 1
        return i

    def bump(self, episode_id, end_ts, max_confidence):
        self.bumps.append((episode_id, end_ts, max_confidence))

    def close(self, episode_id, end_ts):
        self.closed.append((episode_id, end_ts))

    def set_snapshot(self, episode_id, path):
        self.snap[episode_id] = path


@pytest.fixture
def stub(monkeypatch):
    s = _StubIds()
    monkeypatch.setattr(agg_mod, "create_episode", s.create)
    monkeypatch.setattr(agg_mod, "bump_episode", s.bump)
    monkeypatch.setattr(agg_mod, "close_episode", s.close)
    monkeypatch.setattr(agg_mod, "set_episode_snapshot", s.set_snapshot)
    return s


def test_enter_then_bump_then_exit(stub):
    a = EpisodeAggregator()

    ev1, _ = a.observe(camera_id=1, class_name="person", zone_id=None, confidence=0.9, ts=100.0)
    assert ev1 is not None and ev1.kind == "ENTER"
    assert ev1.episode_id == 100

    ev2, _ = a.observe(camera_id=1, class_name="person", zone_id=None, confidence=0.95, ts=100.5)
    assert ev2 is None
    assert stub.bumps == [(100, 100.5, 0.95)]

    exits = a.sweep(now_ts=103.0, hysteresis_for_camera=lambda cid: 2.0)
    assert len(exits) == 1
    assert exits[0].kind == "EXIT"
    assert exits[0].episode_id == 100
    assert stub.closed == [(100, 100.5)]


def test_separate_zones_are_separate_episodes(stub):
    a = EpisodeAggregator()
    ev_a, _ = a.observe(1, "person", zone_id=1, confidence=0.8, ts=1.0)
    ev_b, _ = a.observe(1, "person", zone_id=2, confidence=0.8, ts=1.0)
    assert ev_a is not None and ev_b is not None
    assert ev_a.episode_id != ev_b.episode_id


def test_snapshot_saver_is_called_on_enter(stub):
    a = EpisodeAggregator()
    calls: list[int] = []

    def saver(ep_id: int) -> str:
        calls.append(ep_id)
        return f"/tmp/{ep_id}.jpg"

    a.observe(1, "person", None, 0.9, 10.0, snapshot_saver=saver)
    assert calls == [100]
    assert stub.snap == {100: "/tmp/100.jpg"}


def test_no_exit_before_hysteresis(stub):
    a = EpisodeAggregator()
    a.observe(1, "person", None, 0.9, 50.0)
    # 0.5s later, hysteresis is 5s
    exits = a.sweep(50.5, lambda cid: 5.0)
    assert exits == []
