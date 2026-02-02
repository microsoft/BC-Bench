"""
Failure Mode Analysis TUI for reviewing evaluation results.

Shows expected vs actual diffs side-by-side. Use arrow keys to navigate,
number keys to select failure category. Press Escape to quit.

Copilot wrote most of this code, seems to work, haven't read it all carefully.
"""

import json
from abc import abstractmethod
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


class BaseReviewer(App):
    """Base class for failure mode review TUIs."""

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

    def __init__(self, dataset_path: Path):
        super().__init__()
        self.dataset_path = dataset_path
        self.current_index = 0

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

    @abstractmethod
    def _load_data(self) -> None:
        pass

    @abstractmethod
    def _get_current_result(self) -> dict | None:
        pass

    @abstractmethod
    def _get_expected_patch(self, result: dict) -> str:
        pass

    @abstractmethod
    def _get_progress_text(self, result: dict) -> str:
        pass

    @abstractmethod
    def _get_actual_panel_title(self) -> str:
        pass

    @abstractmethod
    def _save(self) -> None:
        pass

    @abstractmethod
    def _get_item_count(self) -> int:
        pass

    @abstractmethod
    def _get_reviewed_count(self) -> int:
        pass

    def _update_display(self) -> None:
        result = self._get_current_result()
        if not result:
            self.query_one("#progress", Label).update(self._get_empty_message())
            return

        self.query_one("#progress", Label).update(self._get_progress_text(result))

        expected = self._get_expected_patch(result)
        actual = result.get("output", "No output")

        exp_panel = self.query_one("#expected-panel", VerticalScroll)
        act_panel = self.query_one("#actual-panel", VerticalScroll)
        exp_panel.border_title = "Expected (Gold)"
        act_panel.border_title = self._get_actual_panel_title()
        self.query_one("#expected-content", Static).update(self._format_diff(expected))
        self.query_one("#actual-content", Static).update(self._format_diff(actual))
        exp_panel.scroll_home(animate=False)
        act_panel.scroll_home(animate=False)

    def _get_empty_message(self) -> str:
        return "No results to review"

    def _format_diff(self, text: str) -> str:
        if not text:
            return "(empty)"
        lines = []
        for line in text.split("\n"):
            escaped = line.replace("[", r"\[")
            if line.startswith(("+++", "---", "@@")):
                lines.append(f"[cyan]{escaped}[/cyan]")
            elif line.startswith("+"):
                lines.append(f"[green]{escaped}[/green]")
            elif line.startswith("-"):
                lines.append(f"[red]{escaped}[/red]")
            else:
                lines.append(escaped)
        return "\n".join(lines)

    def _format_status(self, result: dict) -> tuple[str, str, str]:
        scores = result.get("scores", {})
        build = scores.get("BuildRate", 0) == 1
        resolved = scores.get("ResolutionRate", 0) == 1
        build_str = "[green]✓[/green]" if build else "[red]✗[/red]"
        resolved_str = "[green]✓[/green]" if resolved else "[red]✗[/red]"
        current_category = result.get("review", {}).get("failure_category") or "[dim]None[/dim]"
        return build_str, resolved_str, current_category

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
        if self.current_index < self._get_item_count() - 1:
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


class InstanceAcrossRunsReviewer(BaseReviewer):
    """Review a single instance across all runs in a directory."""

    TITLE = "Instance Across Runs Review"

    def __init__(self, results_dir: Path, instance_id: str, dataset_path: Path):
        super().__init__(dataset_path)
        self.results_dir = results_dir
        self.instance_id = instance_id
        self.run_results: list[tuple[str, dict, Path]] = []  # (run_id, result_dict, file_path)
        self.expected_patch: str = ""

    def _load_data(self) -> None:
        with open(self.dataset_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    if entry["instance_id"] == self.instance_id:
                        self.expected_patch = entry.get("patch", "")
                        break

        for jsonl_file in sorted(self.results_dir.glob("*.jsonl")):
            run_id = jsonl_file.stem
            with open(jsonl_file, encoding="utf-8") as f:
                for line in f:
                    if not line.strip():
                        continue
                    result = json.loads(line)
                    result_instance_id = result.get("instance_id") or result.get("InstanceID", "")
                    if result_instance_id == self.instance_id:
                        self.run_results.append((run_id, result, jsonl_file))
                        break

    def _get_current_result(self) -> dict | None:
        if not self.run_results or self.current_index >= len(self.run_results):
            return None
        return self.run_results[self.current_index][1]

    def _get_expected_patch(self, result: dict) -> str:
        return self.expected_patch or "Not found in dataset"

    def _get_progress_text(self, result: dict) -> str:
        run_id = self.run_results[self.current_index][0]
        build_str, resolved_str, current_category = self._format_status(result)
        return f"[{self.current_index + 1}/{len(self.run_results)} runs] (reviewed: {self._get_reviewed_count()}) | Run: {run_id} | Build: {build_str} Resolved: {resolved_str} | Category: {current_category} | {self.instance_id}"

    def _get_actual_panel_title(self) -> str:
        run_id = self.run_results[self.current_index][0]
        return f"Actual (Run: {run_id})"

    def _get_empty_message(self) -> str:
        return f"No results found for instance: {self.instance_id}"

    def _get_item_count(self) -> int:
        return len(self.run_results)

    def _get_reviewed_count(self) -> int:
        return sum(1 for _, r, _ in self.run_results if r.get("review", {}).get("failure_category"))

    def _save(self) -> None:
        if not self.run_results or self.current_index >= len(self.run_results):
            return
        _, result, file_path = self.run_results[self.current_index]

        all_results = []
        with open(file_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    all_results.append(json.loads(line))

        for i, r in enumerate(all_results):
            r_instance_id = r.get("instance_id") or r.get("InstanceID", "")
            if r_instance_id == self.instance_id:
                all_results[i] = result
                break

        self._write_results(file_path, all_results)

    @staticmethod
    def _write_results(file_path: Path, results: list[dict]) -> None:
        with open(file_path, "w", encoding="utf-8") as f:
            for r in results:
                if "review" in r:
                    ordered = {"review": r["review"]}
                    ordered.update({k: v for k, v in r.items() if k != "review"})
                    f.write(json.dumps(ordered) + "\n")
                else:
                    f.write(json.dumps(r) + "\n")


class FailureModeAnalysis(BaseReviewer):
    """Review and categorize agent failures in a single results file."""

    TITLE = "Failure Mode Analysis"

    def __init__(self, results_path: Path, dataset_path: Path):
        super().__init__(dataset_path)
        self.results_path = results_path
        self.results: list[dict] = []
        self.unresolved_indices: list[int] = []
        self.dataset_lookup: dict[str, str] = {}

    def _load_data(self) -> None:
        with open(self.dataset_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    entry = json.loads(line)
                    self.dataset_lookup[entry["instance_id"]] = entry.get("patch", "")

        with open(self.results_path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    self.results.append(json.loads(line))

        self.unresolved_indices = [i for i, r in enumerate(self.results) if not r.get("resolved", False) and r.get("scores", {}).get("ResolutionRate", 0) == 0]

    def _get_current_result(self) -> dict | None:
        if not self.unresolved_indices or self.current_index >= len(self.unresolved_indices):
            return None
        return self.results[self.unresolved_indices[self.current_index]]

    def _get_expected_patch(self, result: dict) -> str:
        instance_id = result.get("instance_id") or result.get("InstanceID", "unknown")
        return self.dataset_lookup.get(instance_id, "Not found in dataset")

    def _get_progress_text(self, result: dict) -> str:
        instance_id = result.get("instance_id") or result.get("InstanceID", "unknown")
        build_str, resolved_str, current_category = self._format_status(result)
        return f"[{self.current_index + 1}/{len(self.unresolved_indices)}] (reviewed: {self._get_reviewed_count()}) | Build: {build_str} Resolved: {resolved_str} | Category: {current_category} | {instance_id}"

    def _get_actual_panel_title(self) -> str:
        return "Actual (Agent)"

    def _get_empty_message(self) -> str:
        return "No unresolved results"

    def _get_item_count(self) -> int:
        return len(self.unresolved_indices)

    def _get_reviewed_count(self) -> int:
        return sum(1 for i in self.unresolved_indices if self.results[i].get("review", {}).get("failure_category"))

    def _save(self) -> None:
        InstanceAcrossRunsReviewer._write_results(self.results_path, self.results)


def run_reviewer(results_path: Path, dataset_path: Path) -> None:
    app = FailureModeAnalysis(results_path, dataset_path)
    app.run()


def run_instance_reviewer(results_dir: Path, instance_id: str, dataset_path: Path) -> None:
    app = InstanceAcrossRunsReviewer(results_dir, instance_id, dataset_path)
    app.run()
