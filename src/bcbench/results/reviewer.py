"""
Failure Mode Analysis TUI for reviewing evaluation results.

Shows expected vs actual diffs side-by-side. Use arrow keys to navigate,
number keys to select failure category. Press Escape to quit.

Copilot wrote most of this code, seems to work, haven't read it all carefully.
"""

import json
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, VerticalScroll
from textual.widgets import Footer, Header, Label, Static

# Failure categories (name, description)
FAILURE_CATEGORIES = [
    ("Wrong Solution", "Incorrect approach/logic"),
    ("Syntax Error", "AL syntax issues"),
    ("Incorrect File", "Wrong file edited"),
    ("Missing Using", "Missing using statement for namespace"),
    ("Timeout", "Agent timed out and made no changes"),
    ("Other", "Doesn't fit above"),
]


class FailureModeAnalysis(App):
    """Failure Mode Analysis - review and categorize agent failures."""

    TITLE = "Failure Mode Analysis"

    CSS = """
    #diff-container {
        height: 1fr;
    }
    .diff-panel {
        width: 1fr;
        border: solid green;
    }
    #actual-panel {
        border: solid red;
    }
    """

    BINDINGS = [  # noqa: RUF012
        Binding("right", "next_item", "Next →"),
        Binding("left", "prev_item", "← Prev"),
        Binding("1", "select_category(0)", "Wrong Solution"),
        Binding("2", "select_category(1)", "Syntax Error"),
        Binding("3", "select_category(2)", "Incorrect File"),
        Binding("4", "select_category(3)", "Missing Using"),
        Binding("5", "select_category(4)", "Timeout"),
        Binding("6", "select_category(5)", "Other"),
        Binding("escape", "quit", "Quit"),
    ]

    def __init__(self, results_path: Path, dataset_path: Path):
        super().__init__()
        self.results_path = results_path
        self.dataset_path = dataset_path
        self.results: list[dict] = []
        self.unresolved_indices: list[int] = []
        self.current_index = 0
        self.dataset_lookup: dict[str, str] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield Label("", id="progress")
        with Horizontal(id="diff-container"):
            with VerticalScroll(id="expected-panel", classes="diff-panel"):
                yield Static("", id="expected-content")
            with VerticalScroll(id="actual-panel", classes="diff-panel"):
                yield Static("", id="actual-content")
        yield Footer()

    def on_mount(self) -> None:
        self._load_data()
        self._update_display()

    def _load_data(self) -> None:
        # Load dataset patches
        with open(self.dataset_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    self.dataset_lookup[entry["instance_id"]] = entry.get("patch", "")

        # Load results
        with open(self.results_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.results.append(json.loads(line))

        # Filter to unresolved only
        self.unresolved_indices = [i for i, r in enumerate(self.results) if not r.get("resolved", False) and r.get("scores", {}).get("ResolutionRate", 0) == 0]

    def _get_current_result(self) -> dict | None:
        if not self.unresolved_indices or self.current_index >= len(self.unresolved_indices):
            return None
        return self.results[self.unresolved_indices[self.current_index]]

    def _update_display(self) -> None:
        result = self._get_current_result()
        if not result:
            self.query_one("#progress", Label).update("No unresolved results")
            return

        # Get scores
        scores = result.get("scores", {})
        build = scores.get("BuildRate", 0) == 1
        resolved = scores.get("ResolutionRate", 0) == 1

        # Progress: [1/47] (reviewed: 5) | Build: ✓ Resolved: ✗ | instance_id
        instance_id = result.get("instance_id") or result.get("InstanceID", "unknown")
        reviewed = sum(1 for i in self.unresolved_indices if self.results[i].get("review", {}).get("failure_category"))
        build_str = "[green]✓[/green]" if build else "[red]✗[/red]"
        resolved_str = "[green]✓[/green]" if resolved else "[red]✗[/red]"
        self.query_one("#progress", Label).update(f"[{self.current_index + 1}/{len(self.unresolved_indices)}] (reviewed: {reviewed}) | Build: {build_str} Resolved: {resolved_str} | {instance_id}")

        # Show diffs side by side
        expected = self.dataset_lookup.get(instance_id, "Not found in dataset")
        actual = result.get("output", "No output")

        exp_panel = self.query_one("#expected-panel", VerticalScroll)
        act_panel = self.query_one("#actual-panel", VerticalScroll)
        exp_panel.border_title = "Expected (Gold)"
        act_panel.border_title = "Actual (Agent)"
        self.query_one("#expected-content", Static).update(self._format_diff(expected))
        self.query_one("#actual-content", Static).update(self._format_diff(actual))
        # Scroll to top when changing items
        exp_panel.scroll_home(animate=False)
        act_panel.scroll_home(animate=False)

    def _format_diff(self, text: str) -> str:
        if not text:
            return "(empty)"
        lines = []
        for line in text.split("\n"):
            if line.startswith(("+++", "---", "@@")):
                lines.append(f"[cyan]{line}[/cyan]")
            elif line.startswith("+"):
                lines.append(f"[green]{line}[/green]")
            elif line.startswith("-"):
                lines.append(f"[red]{line}[/red]")
            else:
                lines.append(line)
        return "\n".join(lines)

    def _save(self) -> None:
        with open(self.results_path, "w", encoding="utf-8") as f:
            for result in self.results:
                # Put review at the beginning for easier visibility in JSONL
                if "review" in result:
                    ordered = {"review": result["review"]}
                    ordered.update({k: v for k, v in result.items() if k != "review"})
                    f.write(json.dumps(ordered) + "\n")
                else:
                    f.write(json.dumps(result) + "\n")

    def _set_category(self, idx: int) -> None:
        result = self._get_current_result()
        if not result:
            return
        if "review" not in result:
            result["review"] = {}
        result["review"]["failure_category"] = FAILURE_CATEGORIES[idx][0]
        self._save()
        self.notify(f"Set: {FAILURE_CATEGORIES[idx][0]}")
        self._update_display()

    def action_next_item(self) -> None:
        if self.current_index < len(self.unresolved_indices) - 1:
            self.current_index += 1
            self._update_display()

    def action_prev_item(self) -> None:
        if self.current_index > 0:
            self.current_index -= 1
            self._update_display()

    def action_select_category(self, index: int) -> None:
        if 0 <= index < len(FAILURE_CATEGORIES):
            self._set_category(index)

    def action_quit(self) -> None:
        self._save()
        self.exit()


def run_reviewer(results_path: Path, dataset_path: Path) -> None:
    app = FailureModeAnalysis(results_path, dataset_path)
    app.run()
