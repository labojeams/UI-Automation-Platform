"""
ORM 实体定义。

设计要点：
- id 全部沿用业务前缀 ID（suite_xxx / case_xxx / step_xxx / run_xxx）
- 关系级联：suite -> cases -> steps 全级联删除
- runs / run_logs / step_results 不随 suite 删除而删除（保留历史）
  · runs.target_id 仅记录字符串，不强制外键
- tags / summary 用 SQLite JSON1 列保存
"""
import time

from sqlalchemy import (
    Column, String, Text, Integer, BigInteger, ForeignKey, JSON, Index
)
from sqlalchemy.orm import relationship

from .db import Base


def _now_ms() -> int:
    return int(time.time() * 1000)


class Suite(Base):
    __tablename__ = "suites"

    id = Column(String(64), primary_key=True)
    name = Column(String(255), nullable=False)
    description = Column(Text, default="")
    base_url = Column(String(500), default="")
    tags = Column(JSON, default=list)            # ["demo","search"]
    created_at = Column(BigInteger, default=_now_ms)
    updated_at = Column(BigInteger, default=_now_ms, onupdate=_now_ms)

    cases = relationship(
        "Case",
        back_populates="suite",
        cascade="all, delete-orphan",
        order_by="Case.order_no",
    )


class Case(Base):
    __tablename__ = "cases"

    id = Column(String(64), primary_key=True)
    suite_id = Column(String(64), ForeignKey("suites.id", ondelete="CASCADE"), nullable=False, index=True)
    name = Column(String(255), nullable=False, default="新用例")
    precondition = Column(Text, default="")
    order_no = Column(Integer, default=0)
    status = Column(String(32), default="")       # 最近一次运行状态
    created_at = Column(BigInteger, default=_now_ms)
    updated_at = Column(BigInteger, default=_now_ms, onupdate=_now_ms)

    suite = relationship("Suite", back_populates="cases")
    steps = relationship(
        "Step",
        back_populates="case",
        cascade="all, delete-orphan",
        order_by="Step.order_no",
    )


class Step(Base):
    __tablename__ = "steps"

    id = Column(String(64), primary_key=True)
    case_id = Column(String(64), ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    description = Column(Text, default="")
    expected = Column(Text, default="")
    actual = Column(Text, default="")              # 最近一次执行实际结果
    status = Column(String(32), default="pending") # pending/passed/failed/skipped
    order_no = Column(Integer, default=0)

    case = relationship("Case", back_populates="steps")


class Run(Base):
    __tablename__ = "runs"

    id = Column(String(64), primary_key=True)
    scope = Column(String(16), nullable=False)       # suite / case
    target_id = Column(String(64), index=True)       # suite_id 或 case_id
    target_name = Column(String(255), default="")
    status = Column(String(16), default="running")   # running/done/error
    started_at = Column(BigInteger, default=_now_ms, index=True)
    finished_at = Column(BigInteger)
    summary = Column(JSON)                           # 简化后的 summary（去掉冗余 suite 全量树）

    logs = relationship("RunLog", back_populates="run", cascade="all, delete-orphan")
    step_results = relationship("StepResult", back_populates="run", cascade="all, delete-orphan")


class RunLog(Base):
    __tablename__ = "run_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    ts = Column(BigInteger, nullable=False)
    level = Column(String(16), default="info")
    msg = Column(Text, default="")

    run = relationship("Run", back_populates="logs")


class StepResult(Base):
    __tablename__ = "step_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    run_id = Column(String(64), ForeignKey("runs.id", ondelete="CASCADE"), nullable=False, index=True)
    case_id = Column(String(64), index=True)
    step_id = Column(String(64), index=True)
    idx = Column(Integer, default=0)
    description = Column(Text, default="")
    expected = Column(Text, default="")
    actual = Column(Text, default="")
    status = Column(String(32), default="pending")
    ts = Column(BigInteger, default=_now_ms)

    run = relationship("Run", back_populates="step_results")


class KVConfig(Base):
    __tablename__ = "kv_config"

    key = Column(String(64), primary_key=True)
    value = Column(JSON)


# 复合索引（运行历史按时间倒序的常用查询）
Index("ix_runs_status_started", Run.status, Run.started_at.desc())
Index("ix_step_results_run_idx", StepResult.run_id, StepResult.idx)