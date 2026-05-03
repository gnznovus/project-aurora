from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import timedelta

from sqlalchemy import Select, or_, select
from sqlalchemy.orm import Session, joinedload

from aurora_core.services.models import Agent, Job, JobStatus
from aurora_core.utils.timeutils import utc_now_naive


class RoutingStrategy(ABC):
    @abstractmethod
    def list_candidates(self, db: Session, agent: Agent, limit: int = 20) -> list[Job]:
        raise NotImplementedError


class DefaultStaticRoutingStrategy(RoutingStrategy):
    def __init__(self, heartbeat_ttl_seconds: int) -> None:
        self.heartbeat_ttl_seconds = heartbeat_ttl_seconds

    def is_agent_healthy(self, agent: Agent) -> bool:
        if agent.status != "online":
            return False
        if not agent.last_heartbeat_at:
            return False
        min_heartbeat = utc_now_naive() - timedelta(seconds=self.heartbeat_ttl_seconds)
        return agent.last_heartbeat_at >= min_heartbeat

    def is_eligible(self, agent: Agent, job: Job) -> bool:
        required = set(job.required_tags or [])
        tags = set(agent.tags or [])
        return required.issubset(tags)

    def _base_query(self) -> Select[tuple[Job]]:
        return (
            select(Job)
            .where(
                Job.status == JobStatus.queued,
                or_(Job.next_retry_at.is_(None), Job.next_retry_at <= utc_now_naive()),
            )
            .order_by(Job.created_at.asc())
            .options(joinedload(Job.plugin), joinedload(Job.plugin_version))
        )

    def list_candidates(self, db: Session, agent: Agent, limit: int = 20) -> list[Job]:
        if not self.is_agent_healthy(agent):
            return []
        if agent.active_leases >= agent.max_concurrency:
            return []
        jobs = list(db.scalars(self._base_query().limit(limit)))
        return [job for job in jobs if self.is_eligible(agent, job)]

