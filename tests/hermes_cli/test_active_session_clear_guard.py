"""A canonical chat clear can exempt only its own verified idle runtimes."""

import json
import subprocess
import sys

import pytest

from hermes_cli import active_sessions


@pytest.mark.parametrize("foreign_session", ["tip", "unrelated"])
def test_lineage_mutation_guard_only_exempts_owned_runtime_leases(tmp_path, foreign_session):
    own, refusal = active_sessions.try_acquire_active_session(
        session_id="root", surface="desktop", config={}, registry_home=tmp_path,
        metadata={"live_session_id": "local-runtime"},
    )
    assert refusal is None
    script = """
import json, sys
from hermes_cli.active_sessions import try_acquire_active_session
lease, error = try_acquire_active_session(session_id=sys.argv[2], surface='desktop', config={}, registry_home=sys.argv[1], metadata={'live_session_id':'foreign-runtime'})
assert error is None, error
print(json.dumps({'lease_id':lease.lease_id}), flush=True)
try:
    sys.stdin.readline()
finally:
    lease.release()
"""
    child = subprocess.Popen(
        [sys.executable, "-c", script, str(tmp_path), foreign_session],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        foreign = json.loads(child.stdout.readline())
        with active_sessions.active_session_liveness_guard(
            ["root", "tip"], registry_home=tmp_path,
            allowed_lease_ids={own.lease_id, foreign["lease_id"]},
        ) as blocked:
            assert blocked is (foreign_session == "tip")
        with active_sessions.active_session_liveness_guard("root", registry_home=tmp_path) as blocked:
            assert blocked  # existing destructive callers still count every owner
    finally:
        _out, err = child.communicate("release\n", timeout=30)
        own.release()
    assert child.returncode == 0, err
