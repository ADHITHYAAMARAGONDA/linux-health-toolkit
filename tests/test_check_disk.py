import pathlib
import sys
from types import SimpleNamespace

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'healthcheck'))
import healthcheck as hc


def test_read_only_mounts_are_ignored(monkeypatch):
    parts = [
        SimpleNamespace(mountpoint='/ro', fstype='ext4', opts='ro,relatime'),
        SimpleNamespace(mountpoint='/data', fstype='ext4', opts='rw,relatime'),
    ]
    monkeypatch.setattr(hc.psutil, 'disk_partitions', lambda all=False: parts)
    monkeypatch.setattr(hc.psutil, 'disk_usage', lambda mp: SimpleNamespace(percent=100.0))
    cfg = hc.Config(webhook_url='', disk_pct=80, mem_pct=85, load_per_cpu=1.5,
                    cooldown_s=3600, state_file=pathlib.Path('/tmp/x'), watch_services=())
    assert [f.key for f in hc.check_disk(cfg)] == ['disk:/data']
