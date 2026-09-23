"""Redact accidental content written through Python's conventional logger.

The explicit, default-on developer JSONL trace intentionally records
transcripts and snapshots for diagnosis; it never records audio or API keys.
"""
import logging

class RedactingFilter(logging.Filter):
    FORBIDDEN = ("transcript", "elements", "label", "text", "query_span", "snapshot")
    def filter(self, record):
        msg = record.getMessage().lower()
        if any(k in msg for k in self.FORBIDDEN):
            record.msg = "[redacted runtime content]"
            record.args = ()
        return True

logging.getLogger().addFilter(RedactingFilter())
