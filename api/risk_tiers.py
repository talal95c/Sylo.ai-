TIER_THRESHOLDS = {
    "LOW": (0, 39),
    "MEDIUM": (40, 79),
    "HIGH": (80, 94),
    "CRITICAL": (95, 100),
}


def tier_for(score: int) -> str:
    if not 0 <= score <= 100:
        raise ValueError("score must be between 0 and 100")
    for tier, (minimum, maximum) in TIER_THRESHOLDS.items():
        if minimum <= score <= maximum:
            return tier
    raise ValueError(f"no tier configured for score {score}")
