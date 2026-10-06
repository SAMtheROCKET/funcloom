"""A value set on only one branch cannot become a function input."""

# discount_rate_float has no value unless the script runs directly.
if __name__ == "__main__":
    discount_rate_float = 0.05

# Select line 8: discount_rate_float may be unbound here, so it is refused.
net_amount_float = 120.0 * (1 - discount_rate_float)
