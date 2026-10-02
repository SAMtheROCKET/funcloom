"""Synthetic module with long functions, for `funcloom refine`."""

import math

RATE = 2


def summarize(values, scale=1):
    """Summarize a list of numbers."""
    # Clean
    cleaned = [value for value in values if value is not None]
    count = len(cleaned)
    if count == 0:
        return None
    total = 0
    for value in cleaned:
        total += value * scale
    mean = total / count
    squares = [(value - mean) ** 2 for value in cleaned]
    variance = sum(squares) / count
    deviation = math.sqrt(variance)
    low = min(cleaned)
    high = max(cleaned)
    spread = high - low
    label = "wide" if spread > 10 else "narrow"
    ratio = spread / (deviation or 1)
    flags = []
    if ratio > 3:
        flags.append("spiky")
    if mean > RATE:
        flags.append("high")
    doubled = [value * RATE for value in cleaned]
    helper = lambda x: x + mean
    shifted = [helper(value) for value in doubled]
    extra = sum(shifted)
    notes = {"label": label, "flags": flags}
    parts = [count, total, mean]
    parts.append(variance)
    parts.append(deviation)
    parts.append(low)
    parts.append(high)
    parts.append(spread)
    parts.append(ratio)
    parts.append(extra)
    notes["parts"] = parts
    summary = {"mean": mean, "deviation": deviation, "notes": notes}
    if extra > 1000:
        summary["big"] = True
    result = (summary, len(parts))
    return result


class Report:
    def build(self, rows):
        header = ["name", "value"]
        lines = []
        for row in rows:
            lines.append(f"{row[0]}: {row[1]}")
        total = sum(row[1] for row in rows)
        lines.append(f"total: {total}")
        self.total = total
        count = len(rows)
        average = total / count if count else 0
        lines.append(f"average: {average}")
        best = max(rows, key=lambda row: row[1]) if rows else None
        lines.append(f"best: {best}")
        worst = min(rows, key=lambda row: row[1]) if rows else None
        lines.append(f"worst: {worst}")
        names = sorted(row[0] for row in rows)
        lines.append(", ".join(names))
        width = max((len(name) for name in names), default=0)
        lines.append("-" * width)
        values = [row[1] for row in rows]
        lines.append(str(values))
        extra = [value * 2 for value in values]
        lines.append(str(extra))
        halves = [value / 2 for value in values]
        lines.append(str(halves))
        squares = [value ** 2 for value in values]
        lines.append(str(squares))
        text = "\n".join(lines)
        self.text = text
        summary = {"total": total, "count": count}
        summary["average"] = average
        summary["best"] = best
        summary["worst"] = worst
        summary["width"] = width
        summary["header"] = header
        summary["extra"] = sum(extra)
        summary["halves"] = sum(halves)
        summary["squares"] = sum(squares)
        summary["names"] = names
        return text, summary


def gen(n):
    for index in range(n):
        yield index
    a = 1
    a = 2
    a = 3
    a = 4
    a = 5
    a = 6
    a = 7
    a = 8
    a = 9
    a = 10
    a = 11
    a = 12
    a = 13
    a = 14
    a = 15
    a = 16
    a = 17
    a = 18
    a = 19
    a = 20
    a = 21
    a = 22
    a = 23
    a = 24
    a = 25
    a = 26
    a = 27
    a = 28
    a = 29
    a = 30
    a = 31
    a = 32
    a = 33
    a = 34
    a = 35
    a = 36
    a = 37
    a = 38
    a = 39
    a = 40
    a = 41
    a = 42
    a = 43
    a = 44
    a = 45
    a = 46
    a = 47
    a = 48
    yield a


if __name__ == "__main__":
    print(summarize([4, None, 9, 16], 2))
    print(summarize([]))
    print(Report().build([("north", 3), ("south", 9)]))
    print(list(gen(3)))
