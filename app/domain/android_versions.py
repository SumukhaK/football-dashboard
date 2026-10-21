"""Independent Android app-version input; it never identifies an API release."""


def android_version(value: str | None) -> str | None:
    """Omitted/empty means all; unknown is reserved for missing export versions."""
    if value is None or value == "":
        return None
    if len(value) > 64 or not value.strip() or not value.isprintable():
        raise ValueError("invalid Android app version")
    return value
