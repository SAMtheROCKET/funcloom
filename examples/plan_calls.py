"""Synthetic measurement script whose selected lines call functions."""

import math
import statistics


def format_reading(value_float: float, digits_int: int = 1) -> str:
    """Format a reading with a fixed number of decimal places."""
    return f"{value_float:.{digits_int}f}"


readings_list = [4.0, 9.0, 16.0]
mean_float = statistics.mean(readings_list)
root_float = math.sqrt(mean_float)
label_str = format_reading(root_float, digits_int=2)
