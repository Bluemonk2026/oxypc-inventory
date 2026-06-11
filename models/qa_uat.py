"""
QA / UAT Tracking Models
========================
Implements the full QA-UAT master framework:

  Requirements → Test Cases → Test Executions → Defects
  Requirements → UAT Scenarios
  Releases (linked to QA + UAT sign-off)

Tables
------
  qa_requirements      — functional / non-functional requirements
  qa_test_cases        — test case designs mapped to requirements
  qa_test_executions   — individual test run results
  qa_defects           — defects / bugs raised from executions
  qa_uat_scenarios     — UAT scenarios for business validation
  qa_releases          — release management + sign-off tracking
"""
import uuid
import enum
from datetime import datetime
from utils.timezone import app_now

from sqlalchemy import (
    Column, String, Text, DateTime, Boolean,
    ForeignKey, Enum as SAEnum, Integer
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from database import Base


# ── Enums ─────────────────────────────────────────────────────────────────────

class RequirementSource(str, enum.Enum):
    brd         = "BRD"
    prd         = "PRD"
    user_story  = "User Story"
    change_req  = "Change Request"
    bug_fix     = "Bug Fix"

class RequirementStatus(str, enum.Enum):
    open         = "Open"
    in_progress  = "In Progress"
    done         = "Done"
    deferred     = "Deferred"

class RequirementPriority(str, enum.Enum):
    critical = "Critical"
    high     = "High"
    medium   = "Medium"
    low      = "Low"

class TestCaseType(str, enum.Enum):
    functional   = "Functional"
    negative     = "Negative"
    boundary     = "Boundary"
    integration  = "Integration"
    api          = "API"
    performance  = "Performance"
    regression   = "Regression"
    uat          = "UAT"

class TestCaseStatus(str, enum.Enum):
    draft    = "Draft"
    active   = "Active"
    retired  = "Retired"

class ExecutionStatus(str, enum.Enum):
    pass_   = "Pass"
    fail    = "Fail"
    blocked = "Blocked"
    skipped = "Skipped"

class DefectSeverity(str, enum.Enum):
    critical = "Critical"
    high     = "High"
    medium   = "Medium"
    low      = "Low"

class DefectPriority(str, enum.Enum):
    p1 = "P1 - Immediate"
    p2 = "P2 - High"
    p3 = "P3 - Medium"
    p4 = "P4 - Low"

class DefectStatus(str, enum.Enum):
    new        = "New"
    assigned   = "Assigned"
    in_progress = "In Progress"
    fixed      = "Fixed"
    retest     = "Retest"
    closed     = "Closed"
    reopened   = "Reopened"
    wont_fix   = "Won't Fix"

class UATStatus(str, enum.Enum):
    draft      = "Draft"
    pending    = "Pending Execution"
    pass_      = "Pass"
    fail       = "Fail"
    blocked    = "Blocked"

class ReleaseStatus(str, enum.Enum):
    planned    = "Planned"
    in_qa      = "In QA"
    qa_done    = "QA Done"
    in_uat     = "In UAT"
    uat_done   = "UAT Done"
    approved   = "Approved"
    deployed   = "Deployed"
    rolled_back = "Rolled Back"


# ── Models ────────────────────────────────────────────────────────────────────

class QARequirement(Base):
    """Functional / non-functional requirement from BRD / PRD / user story."""
    __tablename__ = "qa_requirements"

    id          = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    req_code    = Column(String(30), nullable=True)   # e.g. REQ-001
    title       = Column(String(200), nullable=False)
    description = Column(Text, nullable=True)
    source      = Column(SAEnum(RequirementSource, name="req_source_enum"),
                         default=RequirementSource.prd, nullable=False)
    priority    = Column(SAEnum(RequirementPriority, name="req_priority_enum"),
                         default=RequirementPriority.medium, nullable=False)
    status      = Column(SAEnum(RequirementStatus, name="req_status_enum"),
                         default=RequirementStatus.open, nullable=False)
    module      = Column(String(100), nullable=True)  # e.g. "IQC", "Sales"
    created_by  = Column(String(100), nullable=True)
    created_at  = Column(DateTime, default=app_now)
    updated_at  = Column(DateTime, default=app_now, onupdate=app_now)

    # Relationships
    test_cases    = relationship("QATestCase",    back_populates="requirement", lazy="dynamic")
    uat_scenarios = relationship("QAUATScenario", back_populates="requirement", lazy="dynamic")


class QATestCase(Base):
    """Test case design linked to a requirement."""
    __tablename__ = "qa_test_cases"

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    tc_code         = Column(String(30), nullable=True)   # e.g. TC-001
    requirement_id  = Column(UUID(as_uuid=True), ForeignKey("qa_requirements.id"), nullable=True)
    title           = Column(String(200), nullable=False)
    scenario        = Column(Text, nullable=True)        # what is being tested
    preconditions   = Column(Text, nullable=True)
    steps           = Column(Text, nullable=True)        # numbered steps
    expected_result = Column(Text, nullable=True)
    type            = Column(SAEnum(TestCaseType, name="tc_type_enum"),
                             default=TestCaseType.functional, nullable=False)
    status          = Column(SAEnum(TestCaseStatus, name="tc_status_enum"),
                             default=TestCaseStatus.active, nullable=False)
    is_automated    = Column(Boolean, default=False)
    module          = Column(String(100), nullable=True)
    created_by      = Column(String(100), nullable=True)
    created_at      = Column(DateTime, default=app_now)
    updated_at      = Column(DateTime, default=app_now, onupdate=app_now)

    requirement = relationship("QARequirement", back_populates="test_cases")
    executions  = relationship("QATestExecution", back_populates="test_case", lazy="dynamic")
    defects     = relationship("QADefect", back_populates="test_case", lazy="dynamic")


class QATestExecution(Base):
    """Record of one execution run of a test case."""
    __tablename__ = "qa_test_executions"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    test_case_id   = Column(UUID(as_uuid=True), ForeignKey("qa_test_cases.id"), nullable=False)
    status         = Column(SAEnum(ExecutionStatus, name="exec_status_enum"),
                            default=ExecutionStatus.pass_, nullable=False)
    actual_result  = Column(Text, nullable=True)
    notes          = Column(Text, nullable=True)
    build_version  = Column(String(50), nullable=True)   # e.g. "v1.2.3"
    environment    = Column(String(50), default="QA")    # Dev / QA / Staging
    executed_by    = Column(String(100), nullable=True)
    executed_at    = Column(DateTime, default=app_now)

    test_case = relationship("QATestCase", back_populates="executions")


class QADefect(Base):
    """Defect / bug raised from a test execution or ad-hoc."""
    __tablename__ = "qa_defects"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    defect_code         = Column(String(30), nullable=True)    # e.g. BUG-001
    test_case_id        = Column(UUID(as_uuid=True), ForeignKey("qa_test_cases.id"), nullable=True)
    title               = Column(String(200), nullable=False)
    description         = Column(Text, nullable=True)
    steps_to_reproduce  = Column(Text, nullable=True)
    expected_result     = Column(Text, nullable=True)
    actual_result       = Column(Text, nullable=True)
    severity            = Column(SAEnum(DefectSeverity, name="defect_severity_enum"),
                                 default=DefectSeverity.medium, nullable=False)
    priority            = Column(SAEnum(DefectPriority, name="defect_priority_enum"),
                                 default=DefectPriority.p3, nullable=False)
    status              = Column(SAEnum(DefectStatus, name="defect_status_enum"),
                                 default=DefectStatus.new, nullable=False)
    module              = Column(String(100), nullable=True)
    environment         = Column(String(50), default="QA")
    build_version       = Column(String(50), nullable=True)
    assigned_to         = Column(String(100), nullable=True)
    root_cause          = Column(Text, nullable=True)
    resolution          = Column(Text, nullable=True)
    reported_by         = Column(String(100), nullable=True)
    reported_at         = Column(DateTime, default=app_now)
    resolved_at         = Column(DateTime, nullable=True)
    closed_at           = Column(DateTime, nullable=True)

    test_case = relationship("QATestCase", back_populates="defects")


class QAUATScenario(Base):
    """UAT scenario for business validation."""
    __tablename__ = "qa_uat_scenarios"

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    uat_code            = Column(String(30), nullable=True)    # e.g. UAT-001
    requirement_id      = Column(UUID(as_uuid=True), ForeignKey("qa_requirements.id"), nullable=True)
    title               = Column(String(200), nullable=False)
    scenario            = Column(Text, nullable=True)
    acceptance_criteria = Column(Text, nullable=True)
    business_owner      = Column(String(100), nullable=True)
    status              = Column(SAEnum(UATStatus, name="uat_status_enum"),
                                 default=UATStatus.pending, nullable=False)
    executed_by         = Column(String(100), nullable=True)
    executed_at         = Column(DateTime, nullable=True)
    result_notes        = Column(Text, nullable=True)
    feedback            = Column(Text, nullable=True)
    sign_off_by         = Column(String(100), nullable=True)
    sign_off_at         = Column(DateTime, nullable=True)
    created_by          = Column(String(100), nullable=True)
    created_at          = Column(DateTime, default=app_now)

    requirement = relationship("QARequirement", back_populates="uat_scenarios")


class QARelease(Base):
    """Release version with QA + UAT gate tracking."""
    __tablename__ = "qa_releases"

    id             = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    version        = Column(String(50), nullable=False)          # e.g. "v1.3.0"
    title          = Column(String(200), nullable=True)
    description    = Column(Text, nullable=True)
    status         = Column(SAEnum(ReleaseStatus, name="release_status_enum"),
                            default=ReleaseStatus.planned, nullable=False)
    planned_date   = Column(DateTime, nullable=True)
    release_date   = Column(DateTime, nullable=True)
    qa_sign_off_by = Column(String(100), nullable=True)
    qa_sign_off_at = Column(DateTime, nullable=True)
    uat_sign_off_by = Column(String(100), nullable=True)
    uat_sign_off_at = Column(DateTime, nullable=True)
    deployed_by    = Column(String(100), nullable=True)
    notes          = Column(Text, nullable=True)
    rollback_plan  = Column(Text, nullable=True)
    created_by     = Column(String(100), nullable=True)
    created_at     = Column(DateTime, default=app_now)
    updated_at     = Column(DateTime, default=app_now, onupdate=app_now)
