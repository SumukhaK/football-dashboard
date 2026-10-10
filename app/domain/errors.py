"""Domain errors for source operations."""

class SourceUnavailableError(Exception):
    """A telemetry source could not be read.

    :param kind: One of ``permission_denied``, ``quota``, ``unavailable``,
        ``not_found``, or ``invalid_data``.
    :param detail: Human-readable description of the error.
    """

    def __init__(self, kind: str, detail: str) -> None:
        self.kind = kind
        self.detail = detail
        super().__init__(f"[{kind}] {detail}")
