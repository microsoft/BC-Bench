from pathlib import Path

from bcbench.agent.shared.playbook_audit import PlaybookUsageTracker
from bcbench.playbooks import PlaybookSetup

from tests.test_playbooks import write_package


def discover_tracker(tmp_path: Path) -> PlaybookUsageTracker:
    playbook_dir = write_package(tmp_path)
    return PlaybookUsageTracker(
        PlaybookSetup(
            enabled=True,
            mode="discover",
            revision="revision",
            source_dir=playbook_dir,
            router_enabled=True,
        )
    )


def test_records_loaded_route_before_edit(tmp_path: Path):
    tracker = discover_tracker(tmp_path)

    tracker.record_tool_call(
        "mcp__playbooks__route_bug_fix_playbook",
        {"confirmed_paths": ["App/Layers/W1/BaseApp/Warehouse/Activity/Foo.Codeunit.al"]},
    )
    tracker.record_tool_call("Edit", {"file_path": "Foo.Codeunit.al"})

    usage = tracker.finish()

    assert usage is not None
    assert usage.status == "loaded"
    assert usage.playbook_id == "warehouse"
    assert usage.route_event == 1
    assert usage.first_edit_event == 2
    assert usage.routed_before_edit is True
    assert usage.compliant is True


def test_rejects_route_after_edit(tmp_path: Path):
    tracker = discover_tracker(tmp_path)

    tracker.record_tool_call("Edit", {"file_path": "Foo.Codeunit.al"})
    tracker.record_tool_call(
        "mcp__playbooks__route_bug_fix_playbook",
        {"confirmed_paths": ["App/Layers/W1/BaseApp/Warehouse/Activity/Foo.Codeunit.al"]},
    )

    usage = tracker.finish()

    assert usage is not None
    assert usage.compliant is False
    assert usage.violation == "route_bug_fix_playbook was called after the first edit"


def test_requires_exactly_one_route_call(tmp_path: Path):
    tracker = discover_tracker(tmp_path)

    usage = tracker.finish()

    assert usage is not None
    assert usage.status == "missing"
    assert usage.compliant is False
    assert usage.violation == "route_bug_fix_playbook was not called"


def test_rejects_route_without_confirmed_paths(tmp_path: Path):
    tracker = discover_tracker(tmp_path)

    tracker.record_tool_call("mcp__playbooks__route_bug_fix_playbook", {"confirmed_paths": []})

    usage = tracker.finish()

    assert usage is not None
    assert usage.status == "none"
    assert usage.compliant is False
    assert usage.violation == "route_bug_fix_playbook was called without confirmed paths"


def test_selected_mode_records_direct_read(tmp_path: Path):
    playbook_dir = write_package(tmp_path)
    tracker = PlaybookUsageTracker(
        PlaybookSetup(
            enabled=True,
            mode="selected",
            revision="revision",
            playbook_id="warehouse",
            source_dir=playbook_dir,
        )
    )

    tracker.record_tool_call("Read", {"file_path": r".claude\agents\fix-bug\playbooks\warehouse.md"})
    tracker.record_tool_call("Edit", {"file_path": "Foo.Codeunit.al"})

    usage = tracker.finish()

    assert usage is not None
    assert usage.status == "loaded"
    assert usage.playbook_id == "warehouse"
    assert usage.compliant is True
