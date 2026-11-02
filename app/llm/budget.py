class BudgetExceeded(Exception):
    pass


class TokenBudget:
    """Per-plan token cap. Checked BEFORE each call using a rough chars/4 estimate."""

    def __init__(self, limit: int):
        self.limit = limit
        self.used = 0

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    def check(self, estimated: int) -> None:
        if estimated > self.remaining:
            raise BudgetExceeded(f"need ~{estimated} tokens, {self.remaining} left of {self.limit}")

    def charge(self, prompt: int, completion: int) -> None:
        self.used += (prompt or 0) + (completion or 0)


def estimate_tokens(messages: list[dict], max_tokens: int) -> int:
    return sum(len(m.get("content", "")) for m in messages) // 4 + max_tokens
