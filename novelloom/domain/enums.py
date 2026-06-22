from __future__ import annotations

from enum import StrEnum


class BookType(StrEnum):
    MAIN = "main"
    BIOGRAPHY = "biography"
    SIDE_STORY = "side_story"
    ALTERNATE_POV = "alternate_pov"


class NodeKind(StrEnum):
    CHARACTER = "character"
    ORGANIZATION = "organization"
    LOCATION = "location"
    ITEM = "item"
    CONCEPT = "concept"
    WORLD_RULE = "world_rule"
    EVENT = "event"


class EdgeKind(StrEnum):
    RELATIONSHIP = "relationship"
    PARTICIPATES = "participates"
    LOCATED_AT = "located_at"
    CAUSES = "causes"
    PRECEDES = "precedes"
    CONTRADICTS = "contradicts"


class ArtifactKind(StrEnum):
    WORLD_BIBLE = "world_bible"
    EVENT_PLAN = "event_plan"
    VOLUME_OUTLINE = "volume_outline"
    CHAPTER_OUTLINE = "chapter_outline"
    CHAPTER_PROSE = "chapter_prose"
    CHAPTER_SUMMARY = "chapter_summary"
    REVIEW = "review"


class RevisionStatus(StrEnum):
    DRAFT = "draft"
    APPROVED = "approved"
    REJECTED = "rejected"
    SUPERSEDED = "superseded"


class RunStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    WAITING_DECISION = "waiting_decision"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class DecisionStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


class ModelRole(StrEnum):
    WORLD_BUILDER = "world_builder"
    PLOT_REASONER = "plot_reasoner"
    CHAPTER_PLANNER = "chapter_planner"
    WRITER = "writer"
    EXTRACTOR = "extractor"
    CRITIC = "critic"
