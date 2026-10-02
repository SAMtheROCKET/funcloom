"""Synthetic invoice arithmetic for a module-scope extraction proposal."""

base_amount_float: float = 120.0
tax_rate_float: float = 0.10

# Select lines 7-8 to propose a function with two outputs.
tax_amount_float = base_amount_float * tax_rate_float
total_amount_float = base_amount_float + tax_amount_float

print(total_amount_float)
