from datetime import datetime, timezone, timedelta

from panel.timefmt import format_reset_at_epoch, format_reset_epoch


def test_reset_at_epoch_local_format():
    future = datetime.now(timezone.utc) + timedelta(days=2, hours=3)
    s = format_reset_at_epoch(future.timestamp())
    assert len(s) >= 16
    assert s[4] == "-" and s[7] == "-"
    rel = format_reset_epoch(future.timestamp())
    assert "d" in rel or "h" in rel
