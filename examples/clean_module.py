"""Small fully documented example for the implemented milestone-one checks."""

SECONDS_PER_MINUTE_INT = 60


def convert_duration_to_minutes_float(duration_seconds_float: float) -> float:
    """Convert a duration from seconds to minutes.

    Divide by the fixed number of seconds in one minute.

    Args:
        duration_seconds_float (float): Duration measured in seconds.

    Returns:
        float: Duration measured in minutes.

    Warnings:
        Negative durations are preserved rather than rejected.
    """
    duration_minutes_float = (
        duration_seconds_float / SECONDS_PER_MINUTE_INT
    )
    return duration_minutes_float
