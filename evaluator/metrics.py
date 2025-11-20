from __future__ import annotations


class PremiumRequests:
    def __call__(self, *, metadata: dict, **kwargs):
        return {"Premium requests": metadata.get("premium_requests", None)}

class NumberOfSteps:
    def __call__(self, *, metadata: dict, **kwargs):
        return {"Number of steps": metadata.get("number_of_steps", None)}
