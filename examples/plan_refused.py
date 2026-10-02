"""A value set on only one branch cannot become a function input."""

discount_rate_float = 0.0
if __name__ == "__main__":
    discount_rate_float = 0.05

# Select line 8: discount_rate_float is ambiguous here, so it is refused.
net_amount_float = 120.0 * (1 - discount_rate_float)
