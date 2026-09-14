import pytest
from pydantic import TypeAdapter, ValidationError

from app.protocol import AnyMessage, Hello, HelloPayload, Ping, PingPayload, Pong, PongPayload

adapter: TypeAdapter[object] = TypeAdapter(AnyMessage)


@pytest.mark.parametrize(
    "message",
    [
        Hello(ts=1000, id="c-1", d=HelloPayload(last_seq=41, client_version="1.0.0")),
        Hello(ts=1000, d=HelloPayload(client_version="1.0.0")),
        Ping(ts=1000, id="c-2", d=PingPayload(t0=999)),
        Pong(ts=1001, seq=1, d=PongPayload(t0=999, t1=1001)),
        Pong(ts=1001, seq=2, d=PongPayload(t1=1001)),  # unsolicited keepalive, t0 omitted
    ],
)
def test_round_trip(message: Hello | Ping | Pong) -> None:
    raw = message.model_dump_json()
    parsed = adapter.validate_json(raw)
    assert parsed == message
    assert type(parsed) is type(message)


def test_unknown_t_rejected() -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python({"v": 1, "t": "discard", "ts": 1000, "d": {}})


def test_garbage_t_rejected() -> None:
    with pytest.raises(ValidationError):
        adapter.validate_python({"v": 1, "t": "not_a_real_type", "ts": 1000, "d": {}})
