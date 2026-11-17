import contextlib
import json
import logging
import os
import traceback
from pathlib import Path
from typing import Annotated, Literal

import typer

from bcbench.harms import CaptureConfig, export_captures, run_capture
from bcbench.harms_summary import PublicSummary, render_summary, write_summary

harms_app = typer.Typer(help="Harms capture/export and SDK-scored generation; no dataset/result upload.", no_args_is_help=True)


@harms_app.command("config")
def show_config(config: Annotated[Path, typer.Option(exists=True, dir_okay=False)]) -> None:
    value = CaptureConfig.model_validate_json(config.read_text(encoding="utf-8"))
    typer.echo(value.model_dump_json())


@harms_app.command("run")
def run(
    source: Annotated[Literal["generated", "manual"], typer.Option()],
    output: Annotated[Path, typer.Option(help="New private local output directory; never an Actions artifact.")],
    config: Annotated[Path, typer.Option(exists=True, dir_okay=False)],
    cases: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    symbols: Annotated[Path | None, typer.Option(exists=True, file_okay=False)] = None,
    bcal: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    bridge_python: Annotated[Path | None, typer.Option(exists=True, dir_okay=False)] = None,
    evaluate: Annotated[bool, typer.Option("--evaluate/--capture-only", help="Score with public SDK evaluators; capture-only is manual/local only.")] = True,
    ephemeral: Annotated[bool, typer.Option(help="Record that detailed local evidence is discarded at runner teardown.")] = False,
) -> None:
    if os.name != "nt":
        raise typer.BadParameter("BCal harms capture currently requires Windows.")
    if symbols is None or bcal is None or bridge_python is None:
        raise typer.BadParameter("Capture requires --symbols, --bcal and --bridge-python.")
    if (source == "manual") != (cases is not None):
        raise typer.BadParameter("Supply --cases for manual capture only; generated harms come from RedTeam.")
    if source == "generated" and not evaluate:
        raise typer.BadParameter("Public RedTeam generation requires evaluation; capture-only supports supplied cases only.")
    output = output.resolve()
    if output.exists():
        raise typer.BadParameter("Output directory already exists; existing evidence will not be overwritten.")
    output.mkdir(parents=True)
    value: CaptureConfig | None = None
    failed = True
    with (output / "capture.log").open("x", encoding="utf-8") as log:
        root_logger = logging.getLogger()
        original_handlers = root_logger.handlers[:]
        root_logger.handlers = [logging.StreamHandler(log)]
        try:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                value = CaptureConfig.model_validate_json(config.read_text(encoding="utf-8"))
                if source == "manual" and cases is not None:
                    if evaluate:
                        from bcbench.harms_generation import run_manual_evaluation

                        run_manual_evaluation(cases.resolve(), value, bcal.resolve(), bridge_python.resolve(), symbols.resolve(), output)
                    else:
                        run_capture(cases.resolve(), value, bcal.resolve(), bridge_python.resolve(), symbols.resolve(), output)
                else:
                    from bcbench.harms_generation import run_generation

                    run_generation(value, bcal.resolve(), bridge_python.resolve(), symbols.resolve(), output)
                failed = False
        except Exception as exc:
            # Exception details can contain prompts. Keep them local, including validation/subprocess errors.
            traceback.print_exc(file=log)
            typer.echo("Capture failed. Details and any completed captures remain in the local output directory.", err=True)
            raise typer.Exit(1) from exc
        finally:
            if value is not None:
                try:
                    write_summary(output, value, source, evaluated=evaluate, failed=failed, ephemeral=ephemeral)
                except Exception as exc:
                    traceback.print_exc(file=log)
                    root_logger.handlers = original_handlers
                    typer.echo("Summary unavailable; run is incomplete. See private output.", err=True)
                    raise typer.Exit(1) from exc
            root_logger.handlers = original_handlers
    typer.echo("Finished. See summary.md; detailed evidence remains private. No dataset/result upload was performed.")


@harms_app.command("publish-summary")
def publish_summary(
    output: Annotated[Path, typer.Option(exists=True, file_okay=False)],
    destination: Annotated[Path, typer.Option(help="New directory containing only validated public summary JSON/Markdown.")],
) -> None:
    try:
        summary = PublicSummary.model_validate_json((output / "summary.json").read_text(encoding="utf-8"))
        destination.mkdir(parents=True, exist_ok=False)
        (destination / "summary.json").write_text(summary.model_dump_json(indent=2), encoding="utf-8")
        (destination / "summary.md").write_text(render_summary(summary), encoding="utf-8")
    except Exception as exc:
        typer.echo("No summary published: missing or invalid allowlisted summary.", err=True)
        raise typer.Exit(1) from exc


@harms_app.command("export")
def export(output: Annotated[Path, typer.Option(exists=True, file_okay=False)]) -> None:
    try:
        summary = export_captures(output)
    except Exception as exc:
        with (output / "export-error.log").open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        typer.echo("Export failed; see the local export-error.log. Existing datasets are not overwritten.", err=True)
        raise typer.Exit(1) from exc
    typer.echo(json.dumps(summary))


@harms_app.command("report")
def report(output: Annotated[Path, typer.Option(exists=True, file_okay=False)]) -> None:
    try:
        from bcbench.harms_generation import export_sdk_report

        export_sdk_report(output)
    except Exception as exc:
        with (output / "report-error.log").open("a", encoding="utf-8") as log:
            traceback.print_exc(file=log)
        typer.echo("Report export failed; see local report-error.log. Install the redteam extra; raw captures/SDK results remain unchanged.", err=True)
        raise typer.Exit(1) from exc
    typer.echo("Saved local report.xlsx. SDK judgments are not manually confirmed defects; no upload was performed.")
