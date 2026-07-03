"""EventPublisher ABC contract + stub used to verify aggregator emits ENTER/EXIT."""
import pytest

from app.events.publisher import EpisodeEvent, EventPublisher
from app.pipeline import aggregator as agg_mod
from app.pipeline.aggregator import EpisodeAggregator


class RecordingPublisher(EventPublisher):
    def __init__(self):
        self.events: list[EpisodeEvent] = []

    async def publish(self, event: EpisodeEvent) -> None:
        self.events.append(event)


class _Ids:
    def __init__(self):
        self.next_id = 200

    def create(self, camera_id, zone_id, class_name, start_ts, max_confidence, snapshot_path):
        i = self.next_id
        self.next_id += 1
        return i

    def bump(self, *a, **kw): pass
    def close(self, *a, **kw): pass
    def set_snapshot(self, *a, **kw): pass


@pytest.fixture
def stub(monkeypatch):
    s = _Ids()
    monkeypatch.setattr(agg_mod, "create_episode", s.create)
    monkeypatch.setattr(agg_mod, "bump_episode", s.bump)
    monkeypatch.setattr(agg_mod, "close_episode", s.close)
    monkeypatch.setattr(agg_mod, "set_episode_snapshot", s.set_snapshot)
    return s


async def test_publisher_receives_enter_then_exit(stub):
    pub = RecordingPublisher()
    a = EpisodeAggregator()

    ev, _ = a.observe(1, "person", None, 0.9, 100.0)
    assert ev is not None
    await pub.publish(ev)

    exits = a.sweep(110.0, lambda cid: 5.0)
    for ex in exits:
        await pub.publish(ex)

    kinds = [e.kind for e in pub.events]
    assert kinds == ["ENTER", "EXIT"]
    assert pub.events[0].episode_id == pub.events[1].episode_id


def test_publisher_abc_requires_publish():
    class Bad(EventPublisher):
        pass

    with pytest.raises(TypeError):
        Bad()
