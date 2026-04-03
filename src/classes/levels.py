EXP_SCALE = 100

def _fib(n):
    a, b = 1, 1
    for _ in range(n - 1):
        a, b = b, a + b
    return a

def exp_for_level(level: int) -> int:
    """Exp required to advance from level-1 to this level."""
    if level <= 0:
        return 0
    return _fib(level) * EXP_SCALE

def cumulative_exp(level: int) -> int:
    """Total exp required to reach this level from 0."""
    return sum(exp_for_level(l) for l in range(1, level + 1))

def level_from_exp(exp: int) -> tuple[int, int, int]:
    """
    Given total exp, returns:
        (level, exp_into_current_level, exp_needed_for_next_level)
    """
    level = 0
    total = 0
    while True:
        needed = exp_for_level(level + 1)
        if total + needed > exp:
            return level, exp - total, needed - (exp - total)
        total += needed
        level += 1
