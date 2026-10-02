"""Synthetic invoice script with helpers before the calculation."""

import math


def rounded_amount_float(amount_float: float) -> float:
    """Round an amount to two decimal places."""
    return round(amount_float, 2)


base_amount_float = rounded_amount_float(120.456)
tax_rate_float = 0.1
if math.isfinite(base_amount_float):
    status_str = "ok"

tax_amount_float = base_amount_float * tax_rate_float
total_amount_float = base_amount_float + tax_amount_float
