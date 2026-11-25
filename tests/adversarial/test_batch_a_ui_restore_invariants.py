"""Cheap CI regression guards for P0 restore drift and duplicate browser workflow runs."""
from pathlib import Path
from alembic.config import Config
from alembic.script import ScriptDirectory

ROOT = Path(__file__).resolve().parents[2]


def test_encrypted_restore_checks_actual_alembic_head():
    current_head = ScriptDirectory.from_config(
        Config(str(ROOT / "alembic.ini"))
    ).get_current_head()
    assert current_head == "012_batch_e_roles"
    source = (ROOT / "scripts/operations/test_encrypted_restore.py").read_text("utf-8")
    assert f'revision != "{current_head}"' in source
    assert "Restore scratch database already exists; refusing overwrite" in source
    assert 'url.database != SCRATCH_DB' in source


def test_approving_workflow_never_dispatches_another_run_from_ui():
    source = (ROOT / "apps/web/src/components/WorkflowStudioTab.tsx").read_text("utf-8")
    start = source.index("const handleApprovePending =")
    end = source.index("  return (", start)
    handler = source[start:end]
    assert "await api.resolveApproval(requestId, 'approve')" in handler
    assert "setExecutionOutput(resolution.run)" in handler
    assert "executeWorkflow(" not in handler


def test_operations_and_scorecards_have_no_fixture_values_in_real_ui():
    operations = (ROOT / "apps/web/src/components/OperationsTab.tsx").read_text("utf-8")
    accountability = (ROOT / "apps/web/src/components/AccountabilityTab.tsx").read_text("utf-8")
    for fabricated in ("Active Customers (38)", "Due in 3 days", "Kavita Rao",
                       "On Schedule", "Acme Technologies, Enterprise Tier"):
        assert fabricated not in operations
    assert "getOperationsOverview" in operations
    for fabricated in ("9.2% Err", "72.0}%", "?? 36", "|| 50", "|| 3",
                       "Immutable Closed-Loop Verification", "Commit Outcome & Update Scorecards"):
        assert fabricated not in accountability
    assert "Founder-reported observation, not independently verified" in accountability
