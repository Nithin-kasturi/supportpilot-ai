import logging

from app.security.pii import mask_pii

_installed = False


def install_redaction() -> None:
    """Redact secrets and PII from every log record, whichever logger emitted it."""
    global _installed
    if _installed:
        return
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        try:
            message = record.getMessage()
        except Exception:
            return record
        redacted = mask_pii(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        return record

    logging.setLogRecordFactory(factory)
    _installed = True