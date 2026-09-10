from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

from bcbench.playbooks import PlaybookSetup, load_playbook_manifest, route_playbook_for_paths
from bcbench.types import PlaybookUsage

_ROUTER_TOOL = "route_bug_fix_playbook"
_READ_TOOLS = {"read", "view"}
_EDIT_TOOLS = {"apply_patch", "edit", "multiedit", "notebookedit", "write"}


@dataclass
class PlaybookUsageTracker:
    setup: PlaybookSetup
    _event_index: int = 0
    _first_edit_event: int | None = None
    _route_calls: list[tuple[int, list[str]]] = field(default_factory=list)
    _playbook_reads: list[tuple[int, str]] = field(default_factory=list)

    def record_tool_call(self, tool_name: str, tool_input: object) -> None:
        self._event_index += 1
        normalized_name = tool_name.casefold()
        if normalized_name in _EDIT_TOOLS and self._first_edit_event is None:
            self._first_edit_event = self._event_index

        if not isinstance(tool_input, dict):
            return
        input_data = cast(dict[str, object], tool_input)

        if normalized_name.endswith(_ROUTER_TOOL):
            confirmed_paths = input_data.get("confirmed_paths")
            if isinstance(confirmed_paths, list) and all(isinstance(path, str) for path in confirmed_paths):
                self._route_calls.append((self._event_index, cast(list[str], confirmed_paths)))
            else:
                self._route_calls.append((self._event_index, []))

        if normalized_name in _READ_TOOLS:
            path = input_data.get("file_path") or input_data.get("path")
            if isinstance(path, str) and "/playbooks/" in path.replace("\\", "/").casefold():
                self._playbook_reads.append((self._event_index, Path(path).name.casefold()))

    def finish(self) -> PlaybookUsage | None:
        source_dir = self.setup.source_dir
        if not self.setup.enabled or self.setup.mode is None or source_dir is None:
            return None
        if self.setup.router_enabled:
            return self._finish_routed_usage(source_dir)
        return self._finish_selected_usage(source_dir)

    def _finish_routed_usage(self, source_dir: Path) -> PlaybookUsage:
        if not self._route_calls:
            return PlaybookUsage(
                status="missing",
                first_edit_event=self._first_edit_event,
                compliant=False,
                violation="route_bug_fix_playbook was not called",
            )

        route_event, confirmed_paths = self._route_calls[0]
        route = route_playbook_for_paths(source_dir, confirmed_paths)
        routed_before_edit = self._first_edit_event is None or route_event < self._first_edit_event
        violation = None
        if not confirmed_paths:
            violation = "route_bug_fix_playbook was called without confirmed paths"
        elif len(self._route_calls) > 1:
            violation = f"route_bug_fix_playbook was called {len(self._route_calls)} times"
        elif not routed_before_edit:
            violation = "route_bug_fix_playbook was called after the first edit"

        return PlaybookUsage(
            status=route.status,
            playbook_id=route.playbook_id,
            matching_playbook_ids=route.matching_playbook_ids,
            confirmed_paths=confirmed_paths,
            route_event=route_event,
            first_edit_event=self._first_edit_event,
            routed_before_edit=routed_before_edit,
            compliant=violation is None,
            violation=violation,
        )

    def _finish_selected_usage(self, source_dir: Path) -> PlaybookUsage:
        if self.setup.playbook_id is None:
            return PlaybookUsage(status="missing", first_edit_event=self._first_edit_event, compliant=False, violation="selected playbook id is missing")

        manifest = load_playbook_manifest(source_dir)
        selected = next(playbook for playbook in manifest.playbooks if playbook.id == self.setup.playbook_id)
        reads = [event for event, filename in self._playbook_reads if filename == selected.file.casefold()]
        if not reads:
            return PlaybookUsage(
                status="missing",
                playbook_id=selected.id,
                matching_playbook_ids=[selected.id],
                first_edit_event=self._first_edit_event,
                compliant=False,
                violation=f"{selected.file} was not read",
            )

        read_event = reads[0]
        read_before_edit = self._first_edit_event is None or read_event < self._first_edit_event
        violation = None if read_before_edit else f"{selected.file} was read after the first edit"
        return PlaybookUsage(
            status="loaded",
            playbook_id=selected.id,
            matching_playbook_ids=[selected.id],
            route_event=read_event,
            first_edit_event=self._first_edit_event,
            routed_before_edit=read_before_edit,
            compliant=violation is None,
            violation=violation,
        )
