"""
Dataset Review TUI for browsing dataset entries.

Shows dataset entry info and problem statement. Use arrow keys to navigate.
If results directory is provided, shows resolution stats across runs.

Copilot wrote all of this code, seems to work, haven't read it.
"""

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Label, Static

from bcbench.dataset import DatasetEntry, load_dataset_entries


class DatasetReviewer(App):
    """TUI for reviewing dataset entries."""

    TITLE = "Dataset Review"

    CSS = """
    #content-container {
        height: 1fr;
    }
    .content-panel {
        height: 1fr;
        border: solid blue;
    }
    #info-panel {
        height: auto;
        max-height: 12;
    }
    #info-columns {
        height: auto;
    }
    .info-column {
        width: 1fr;
        height: auto;
    }
    #problem-panel {
        border: solid green;
    }
    """

    BINDINGS = [  # noqa: RUF012
        Binding("right", "next_item", "Next →"),
        Binding("left", "prev_item", "← Prev"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(self, dataset_path: Path, results_dir: Path | None = None):
        super().__init__()
        self.dataset_path = dataset_path
        self.results_dir = results_dir
        self.entries: list[DatasetEntry] = []
        self.current_index = 0
        self.resolution_cache: dict[str, tuple[int, int, list[str]]] = {}  # instance_id -> (resolved, total, failure_categories)

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("", id="progress")
        with Vertical(id="content-container"):
            with VerticalScroll(id="info-panel", classes="content-panel"), Horizontal(id="info-columns"):
                yield Static("", id="info-left", classes="info-column")
                yield Static("", id="info-right", classes="info-column")
            with VerticalScroll(id="problem-panel", classes="content-panel"):
                yield Static("", id="problem-content")
        yield Footer()

    def on_mount(self) -> None:
        self._load_data()
        self._update_display()

    def _load_data(self) -> None:
        self.entries = load_dataset_entries(self.dataset_path)
        if self.results_dir:
            self._load_resolution_stats()

    def _load_resolution_stats(self) -> None:
        if not self.results_dir or not self.results_dir.exists():
            return

        for jsonl_file in self.results_dir.glob("*.jsonl"):
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        result = json.loads(line)
                        instance_id = result.get("instance_id") or result.get("InstanceID", "")
                        if not instance_id:
                            continue

                        scores = result.get("scores", {})
                        resolved = scores.get("ResolutionRate", 0) == 1

                        if instance_id not in self.resolution_cache:
                            self.resolution_cache[instance_id] = (0, 0, [])

                        current_resolved, current_total, failure_cats = self.resolution_cache[instance_id]

                        # Collect failure category if not resolved
                        if not resolved:
                            failure_cat = result.get("review", {}).get("failure_category")
                            if failure_cat:
                                failure_cats = [*failure_cats, failure_cat]

                        self.resolution_cache[instance_id] = (
                            current_resolved + (1 if resolved else 0),
                            current_total + 1,
                            failure_cats,
                        )
                    except json.JSONDecodeError:
                        continue

    def _get_current_entry(self) -> DatasetEntry | None:
        if not self.entries or self.current_index >= len(self.entries):
            return None
        return self.entries[self.current_index]

    def _get_resolution_text(self, instance_id: str) -> str:
        if not self.results_dir:
            return ""
        if instance_id not in self.resolution_cache:
            return " | [dim]No runs found[/dim]"
        resolved, total, failure_cats = self.resolution_cache[instance_id]
        if resolved == total:
            return f" | [green]{resolved}/{total} resolved[/green]"

        # Build failure category summary
        failure_text = ""
        if failure_cats:
            from collections import Counter

            counts = Counter(failure_cats)
            failure_text = " | " + ", ".join(f"{cat}: {cnt}" for cat, cnt in counts.most_common())

        if resolved == 0:
            return f" | [red]{resolved}/{total} resolved[/red]{failure_text}"
        return f" | [yellow]{resolved}/{total} resolved[/yellow]{failure_text}"

    def _format_entry_info_left(self, entry: DatasetEntry) -> str:
        lines = [
            f"[cyan bold]Repo:[/cyan bold] {entry.repo}",
            f"[cyan bold]Instance ID:[/cyan bold] {entry.instance_id}",
            f"[cyan bold]Base Commit:[/cyan bold] {entry.base_commit}",
            f"[cyan bold]Created At:[/cyan bold] {entry.created_at}",
            f"[cyan bold]Version:[/cyan bold] {entry.environment_setup_version}",
        ]

        # Project Paths
        lines.append("")
        lines.append("[cyan bold]Project Paths:[/cyan bold]")
        for path in entry.project_paths:
            lines.append(f"  {path}")

        return "\n".join(lines)

    def _format_entry_info_right(self, entry: DatasetEntry) -> str:
        lines = []

        # Metadata
        metadata = entry.metadata.model_dump()
        if any(v is not None for v in metadata.values()):
            lines.append("[bold]Metadata:[/bold]")
            for field_name, field_value in metadata.items():
                if field_value is not None:
                    display_name = field_name.replace("_", " ").title()
                    lines.append(f"  [dim]{display_name}:[/dim] {field_value}")
            lines.append("")

        # FAIL_TO_PASS tests
        lines.append("[bold]FAIL_TO_PASS:[/bold]")
        if entry.fail_to_pass:
            for test in entry.fail_to_pass:
                lines.append(f"  [magenta]{test.codeunitID}[/magenta]: {', '.join(test.functionName)}")
        else:
            lines.append("  [dim]None[/dim]")

        # PASS_TO_PASS tests
        lines.append("")
        lines.append("[bold]PASS_TO_PASS:[/bold]")
        if entry.pass_to_pass:
            for test in entry.pass_to_pass:
                lines.append(f"  [magenta]{test.codeunitID}[/magenta]: {', '.join(test.functionName)}")
        else:
            lines.append("  [dim]None[/dim]")

        return "\n".join(lines)

    def _update_display(self) -> None:
        entry = self._get_current_entry()
        if not entry:
            self.query_one("#progress", Label).update("No entries in dataset")
            return

        resolution_text = self._get_resolution_text(entry.instance_id)
        progress_text = f"[{self.current_index + 1}/{len(self.entries)}]{resolution_text} | {entry.instance_id}"
        self.query_one("#progress", Label).update(progress_text)

        info_panel = self.query_one("#info-panel", VerticalScroll)
        problem_panel = self.query_one("#problem-panel", VerticalScroll)
        info_panel.border_title = "Entry Information"
        problem_panel.border_title = "Problem Statement"

        self.query_one("#info-left", Static).update(self._format_entry_info_left(entry))
        self.query_one("#info-right", Static).update(self._format_entry_info_right(entry))
        self.query_one("#problem-content", Static).update(entry.get_task())

        info_panel.scroll_home(animate=False)
        problem_panel.scroll_home(animate=False)

    def action_next_item(self) -> None:
        if self.current_index < len(self.entries) - 1:
            self.current_index += 1
            self._update_display()

    def action_prev_item(self) -> None:
        if self.current_index > 0:
            self.current_index -= 1
            self._update_display()

    def action_quit(self) -> None:
        self.exit()


def run_dataset_reviewer(dataset_path: Path, results_dir: Path | None = None) -> None:
    app = DatasetReviewer(dataset_path, results_dir)
    app.run()
