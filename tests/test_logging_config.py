import json
import logging
from datetime import datetime, timezone

from isee.logging_config import JsonFormatter


def test_json_formatter_emits_structured_utc_log_record() -> None:
    record = logging.LogRecord(
        name="isee.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="collector started",
        args=(),
        exc_info=None,
    )

    entry = json.loads(JsonFormatter().format(record))

    assert entry["level"] == "INFO"
    assert entry["logger"] == "isee.test"
    assert entry["message"] == "collector started"
    timestamp = datetime.fromisoformat(entry["timestamp"])
    assert timestamp.utcoffset() == timezone.utc.utcoffset(None)
