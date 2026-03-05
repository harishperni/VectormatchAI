def weighted_score(
    semantic: float,
    skill: float,
    experience: float,
    domain: float,
) -> float:
    value = (0.40 * semantic) + (0.30 * skill) + (0.20 * experience) + (0.10 * domain)
    return round(value, 2)
