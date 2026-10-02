"""Synthetic sales script used to demonstrate `funcloom modularize`."""

import statistics
from collections import Counter

tax_rate = 0.1
currency = "EUR"


def with_tax(amount):
    """Return an amount including tax."""
    return round(amount * (1 + tax_rate), 2)


class Sale:
    """One sale record."""

    def __init__(self, region, amount):
        self.region = region
        self.amount = amount


# Load the records
rows = [("north", 120.0), ("south", 80.5), ("north", 42.0), ("east", 7.25)]
sales = [Sale(region, amount) for region, amount in rows]

# Clean the data
sales = [sale for sale in sales if sale.amount > 10]
regions = Counter(sale.region for sale in sales)

# Compute totals
totals = {}
for sale in sales:
    totals[sale.region] = totals.get(sale.region, 0) + with_tax(sale.amount)
if len(totals) > 1:
    busiest = max(totals, key=totals.get)
else:
    busiest = None
average = statistics.mean(totals.values())

if __name__ == "__main__":
    print(currency, totals)
    print("busiest:", busiest, "regions:", dict(regions))
    print(f"average {average:.2f}")
