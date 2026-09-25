from __future__ import annotations

from typing import TYPE_CHECKING

from bcbench.types import AgentMetrics

if TYPE_CHECKING:
    from bcbench.agent.shared.history_gateway import HistoryGateway


def attach_history_metrics(metrics: AgentMetrics | None, gateway: HistoryGateway | None) -> AgentMetrics | None:
    if gateway is None:
        return metrics
    return (metrics or AgentMetrics()).model_copy(update={"investigation": gateway.trace})
