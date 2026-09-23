"""$5/hr cost guard with on-screen alerts. Tracks est. input tokens per Jev call."""
import time

HOURLY_CAP_USD = 5.0
WARN_RATIO = 0.8
PRICE_PER_MTOK = 0.042  # Jev input only, output free

class CostGuard:
    def __init__(self):
        self.window_start = time.time()
        self.spent = 0.0

    def _reset_if_hour_passed(self):
        if time.time() - self.window_start > 3600:
            self.window_start = time.time()
            self.spent = 0.0

    def record(self, est_input_tokens: int) -> dict:
        self._reset_if_hour_passed()
        self.spent += (est_input_tokens / 1e6) * PRICE_PER_MTOK
        elapsed = max(1, time.time() - self.window_start)
        pace = self.spent / elapsed * 3600  # projected hourly
        return {"spent": round(self.spent, 4), "projected": round(pace, 4),
                "warn": pace >= HOURLY_CAP_USD * WARN_RATIO,
                "blocked": self.spent >= HOURLY_CAP_USD}

    @staticmethod
    def estimate_tokens(state: dict, questions: dict) -> int:
        # rough: 1 token ~ 4 chars of serialized payload
        return (len(str(state)) + len(str(questions))) // 4 + 100
