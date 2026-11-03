import os

from postbox import watch
from postbox.transport import LocalTransport, Transport, TransportError


class Broken(Transport):
    kind = "broken"

    def __init__(self, inner):
        self.inner = inner
        self.down = True

    def list(self, sub="", recursive=False, with_hash=False):
        if self.down:
            raise TransportError("network down")
        return self.inner.list(sub, with_hash=with_hash)

    def read(self, name):
        return self.inner.read(name)

    def create(self, name, data):
        return self.inner.create(name, data)

    def replace(self, name, data):
        self.inner.replace(name, data)

    def delete(self, name):
        return self.inner.delete(name)


def touch(path, text="x", mtime=1_700_000_000):
    full = os.path.join(path, text if not text.endswith(".md") else text)
    with open(full, "w", encoding="utf-8") as fh:
        fh.write("body\n")
    os.utime(full, (mtime, mtime))


def test_first_run_reports_change_then_goes_quiet(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    touch(str(box), "a.md")
    state = str(tmp_path / "state")
    transport = LocalTransport(str(box))

    code, out1 = watch.run(transport, ["."], state)
    assert code == 10           # no baseline yet: the agent must look
    code, out2 = watch.run(transport, ["."], state)
    assert code == 0
    assert out1 == out2         # byte-identical => a monitor does not wake the model


def test_change_appends_a_diff_and_settles(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    touch(str(box), "a.md")
    state = str(tmp_path / "state")
    transport = LocalTransport(str(box))
    watch.run(transport, ["."], state)
    _, base = watch.run(transport, ["."], state)

    touch(str(box), "b.md", mtime=1_700_000_100)
    code, out = watch.run(transport, ["."], state)
    assert code == 10
    assert "CHANGED|+1|-0" in out
    assert "+ b.md" in out
    assert base not in out

    code, out3 = watch.run(transport, ["."], state)
    assert code == 0
    assert "b.md" in out3


def test_single_blip_is_silent_and_second_is_reported_once(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    touch(str(box), "a.md")
    state = str(tmp_path / "state")
    good = LocalTransport(str(box))
    watch.run(good, ["."], state)
    _, baseline = watch.run(good, ["."], state)

    broken = Broken(good)
    code, out = watch.run(broken, ["."], state)
    assert code == 0 and out == baseline      # a blip must not wake anyone

    code, out = watch.run(broken, ["."], state)
    assert code == 11
    assert watch.MARK % "transport_unreachable" in out
    marker_line = [l for l in out.splitlines() if l.startswith("STATUS|")][0]

    code, out_again = watch.run(broken, ["."], state)
    assert code == 11 and out_again == out   # constant: one wake-up per outage
    assert marker_line in out_again

    broken.down = False
    code, out_up = watch.run(broken, ["."], state)
    assert "STATUS|" not in out_up           # recovery is visible exactly once
    assert code == 0
    assert out_up == baseline


def test_empty_listing_does_not_wipe_the_baseline(tmp_path):
    box = tmp_path / "box"
    box.mkdir()
    touch(str(box), "a.md")
    state = str(tmp_path / "state")
    good = LocalTransport(str(box))
    watch.run(good, ["."], state)
    watch.run(good, ["."], state)

    empty = tmp_path / "empty"
    empty.mkdir()
    code, out = watch.run(LocalTransport(str(empty)), ["."], state)
    assert code == 0                         # treated as a blip, baseline intact
    code, out = watch.run(LocalTransport(str(empty)), ["."], state)
    assert code == 11 and "DEGRADED" in out

    recovered = watch.run(good, ["."], state)
    assert "a.md" in recovered[1]


def test_no_baseline_and_down_is_an_explicit_error(tmp_path):
    code, out = watch.run(Broken(None), ["."], str(tmp_path / "s"))
    assert code == 11
    assert "ERROR|" in out and "DEGRADED|no_baseline" in out
