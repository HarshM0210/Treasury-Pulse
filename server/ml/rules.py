"""Single source of truth for liquidity levels and risk grades."""

LEVELS = ["EMERGENCY", "CRITICAL", "WARNING", "OK", "SURPLUS"]  # worst -> best
SEVERITY = {level: i for i, level in enumerate(LEVELS)}
ALERT_LEVELS = {"EMERGENCY", "CRITICAL", "WARNING"}

WARNING_PCT = 0.10   # headroom below 10%  -> WARNING
CRITICAL_PCT = 0.05  # headroom below 5%   -> CRITICAL
SURPLUS_PCT = 0.20   # headroom above 20%  -> SURPLUS (deployable)


def classify(position, threshold):
    """Liquidity level of one position against its minimum balance."""
    position, threshold = float(position), float(threshold)
    if threshold <= 0:
        return "SURPLUS" if position >= 0 else "EMERGENCY"
    if position < threshold:
        return "EMERGENCY"
    headroom = (position - threshold) / threshold
    if headroom < CRITICAL_PCT:
        return "CRITICAL"
    if headroom < WARNING_PCT:
        return "WARNING"
    if headroom <= SURPLUS_PCT:
        return "OK"
    return "SURPLUS"


def worst(levels):
    levels = list(levels)
    return min(levels, key=SEVERITY.__getitem__) if levels else "OK"


def deployable_surplus(position, threshold):
    """Cash above threshold + 20% that can be deployed."""
    return max(0.0, float(position) - (1 + SURPLUS_PCT) * float(threshold))


# Counterparty risk grade from R in [0, 1] (probability that a payment does
# not arrive in full and on time).
RATING_BANDS = [(0.01, "A"), (0.05, "B"), (0.18, "C"), (1.01, "D")]
# Representative R for each grade, used by the rating-shift what-if.
RATING_R = {"A": 0.005, "B": 0.03, "C": 0.115, "D": 0.25}
# Extra settlement delay (days) assumed per grade in the rating-shift what-if.
RATING_DELAY_DAYS = {"A": 0, "B": 2, "C": 5, "D": 8}


def grade(r):
    for upper, label in RATING_BANDS:
        if r < upper:
            return label
    return "D"
