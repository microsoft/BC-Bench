"""Data-query category: compile and run an AL query in a BC container and return its rows."""

import logging
import subprocess
from pathlib import Path
from string import Template
from typing import Literal

from bcbench_core.filesystem import remove_tree

from bcbench.config import get_config
from bcbench.exceptions import BuildError, BuildTimeoutExpired
from bcbench.operations.bc_operations import escape_ps_string
from bcbench.operations.setup_operations import bootstrap_app_json
from bcbench.types import ContainerConfig

logger = logging.getLogger(__name__)
_config = get_config()


# --- data-query category: compile + run an AL query and capture its rows via a wrapped API query ---

# API metadata injected into a generated/gold query so it is exposed over OData and can be fetched.
_QUERY_API_PUBLISHER = "bcbench"
_QUERY_API_GROUP = "eval"
_QUERY_API_VERSION = "v1.0"


def _safe_object_name(object_id: int) -> str:
    """A short, unique, always-valid query object name.

    The object name is irrelevant to a query's result set (we score by comparing data, not
    identifiers), but AL requires it to be a valid identifier of <=30 characters and unique in
    the tenant. Normalizing it keeps the benchmark focused on query logic instead of failing an
    otherwise-correct query just because the agent chose a long/descriptive name (AL0305).
    """
    return f"BCBenchQuery{object_id}"


def _entity_set_name(object_id: int) -> str:
    """Per-object OData entity set so the generated and gold API queries don't collide on route."""
    return f"bcbenchResults{object_id}"


def _entity_name(object_id: int) -> str:
    return f"bcbenchResult{object_id}"


def _query_api_properties(object_id: int) -> str:
    return (
        "QueryType = API;\n"
        f"    APIPublisher = '{_QUERY_API_PUBLISHER}';\n"
        f"    APIGroup = '{_QUERY_API_GROUP}';\n"
        f"    APIVersion = '{_QUERY_API_VERSION}';\n"
        f"    EntityName = '{_entity_name(object_id)}';\n"
        f"    EntitySetName = '{_entity_set_name(object_id)}';"
    )


def wrap_query_as_api(query_text: str, object_id: int) -> str:
    """Turn a plain AL query object into an API query the harness can fetch over OData.

    Reassigns the object id and normalizes the object name (so generated and gold apps don't
    collide and long names don't cause AL0305), drops any existing ``QueryType`` line, and
    injects the API properties right after the object's opening brace. Pure string transform so
    it can be unit-tested without a container.
    """
    import re

    safe_name = _safe_object_name(object_id)
    # AL keywords are case-insensitive; match `query`/`QueryType` in any casing.
    text, replaced = re.subn(
        r'(\bquery\s+)\d+\s+("(?:[^"\\]|\\.)*"|\w+)',
        rf"\g<1>{object_id} {safe_name}",
        query_text,
        count=1,
        flags=re.IGNORECASE,
    )
    if replaced == 0:
        raise BuildError("query-wrap", f"No AL query object declaration found in generated output:\n{query_text}")

    text = re.sub(r"\bQueryType\s*=\s*\w+\s*;", "", text, count=1, flags=re.IGNORECASE)

    brace_index = text.find("{")
    if brace_index == -1:
        raise BuildError("query-wrap", f"Generated query has no object body ('{{' not found):\n{query_text}")
    return f"{text[: brace_index + 1]}\n    {_query_api_properties(object_id)}\n{text[brace_index + 1 :]}"


# The gold/generated query is compiled, published and read in four clearly-delimited, individually
# logged phases. This whole script runs as one opaque `pwsh -Command` blob, so without the phase
# markers a failure or timeout is unattributable; `Write-QueryPhase` prints a timestamped
# `[query-<suffix>] Phase N/4: ...` line so a CI run shows exactly which phase it reached.
_QUERY_RUN_TEMPLATE = Template(
    """
Import-Module BcContainerHelper -Force -DisableNameChecking
Import-Module '$app_utils_path' -Force
$$ErrorActionPreference = 'Stop'

function Write-QueryPhase([string]$$phase) {
    Write-Host "[query-$suffix] $$((Get-Date).ToString('HH:mm:ss')) $$phase"
}

$$password = ConvertTo-SecureString '$password' -AsPlainText -Force
$$credential = New-Object System.Management.Automation.PSCredential('$username', $$password)

# --- Phase 1/4: cleanup ---
# Remove any app left installed by a previous run of the same suffix so re-running against the
# same container doesn't fail with an object-ID conflict on the fixed 50100/50101 range.
Write-QueryPhase 'Phase 1/4: removing any app from a prior run'
UnInstall-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -force -doNotSaveData -ErrorAction SilentlyContinue
UnPublish-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -ErrorAction SilentlyContinue

# --- Phase 2/4: compile + publish ---
# Compile + publish the wrapped API query with the same proven helper the other categories use
# (clears/sets an explicit .alpackages symbol folder, GenerateReportLayout=No, ForceSync,
# dependencyPublishingOption=ignore) so Base Application symbols resolve reliably.
Write-QueryPhase 'Phase 2/4: compiling + publishing the wrapped API query'
Invoke-AppBuildAndPublish -containerName '$container_name' -appProjectFolder '$app_dir' -credential $$credential -skipVerification -useDevEndpoint

try {
    # --- Phase 3/4: read rows ---
    # Read the query's rows over the OData/API endpoint from *inside* the container, so we don't depend
    # on host->container name resolution or published ports (the runner does not update its hosts file).
    # Basic auth header is built by hand rather than via -Credential: PowerShell 7 (used inside the
    # container) refuses -Credential over plain HTTP, and a manual header works on both 5.1 and 7.
    Write-QueryPhase 'Phase 3/4: reading rows over the OData endpoint'
    $$json = Invoke-ScriptInBcContainer -containerName '$container_name' -argumentList $$credential, '$publisher', '$group', '$version', '$entity_set', '$company' -scriptblock {
        param($$cred, $$pub, $$grp, $$ver, $$eset, $$company)
        $$pair = "$$($$cred.UserName):$$($$cred.GetNetworkCredential().Password)"
        $$headers = @{ Authorization = 'Basic ' + [Convert]::ToBase64String([Text.Encoding]::ASCII.GetBytes($$pair)) }
        $$base = 'http://localhost:7048/BC/api'
        # Pin the gold query to the company the agent queried via MCP so the comparison is against the
        # same data. The company is required upstream, so a missing one here is a hard error, not a
        # silent fall-through to an arbitrary company.
        $$companies = (Invoke-RestMethod -Uri "$$base/v2.0/companies" -Headers $$headers).value
        $$companyId = ($$companies | Where-Object { $$_.name -eq $$company } | Select-Object -First 1).id
        if (-not $$companyId) { throw "Company '$$company' not found among $$($$companies.name -join ', ')" }
        # Follow @odata.nextLink so large result sets aren't silently truncated to the first page.
        $$rows = [System.Collections.Generic.List[object]]::new()
        $$uri = "$$base/$$pub/$$grp/$$ver/companies($$companyId)/$$eset"
        while ($$uri) {
            $$page = Invoke-RestMethod -Uri $$uri -Headers $$headers
            if ($$null -ne $$page.value) { foreach ($$row in $$page.value) { $$rows.Add($$row) } }
            $$uri = $$page.'@odata.nextLink'
        }
        $$rows | ConvertTo-Json -Depth 10 -Compress
    }
    $$json | Out-File -FilePath '$result_file' -Encoding utf8
    Write-QueryPhase 'Phase 3/4: rows written'
}
finally {
    # --- Phase 4/4: teardown ---
    # Best-effort teardown so the container doesn't accumulate throwaway apps between runs.
    Write-QueryPhase 'Phase 4/4: tearing down the throwaway app'
    UnInstall-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -force -doNotSaveData -ErrorAction SilentlyContinue
    UnPublish-BcContainerApp -containerName '$container_name' -name '$app_name' -publisher '$app_publisher' -ErrorAction SilentlyContinue
}
""".strip()
)


def execute_al_query(query_text: str, container: ContainerConfig, version: str, work_root: Path, suffix: Literal["generated", "gold"], company: str) -> list[dict]:
    """Compile + publish an AL query (wrapped as an API query) to the container and return its rows.

    Builds a throwaway app under ``work_root/.bcbench-query-<suffix>``, compiles + publishes it,
    then reads the query's OData endpoint. ``company`` pins which company the query runs against (so
    the gold matches the company the agent queried via MCP) and is required — the query must run
    against a known company, never an arbitrary default. Raises :class:`BuildError` if the query does
    not compile or publish.

    NOTE: the container-side steps (compile/publish/OData fetch) require a running BC container
    and have not been validated locally; the wrapping and comparison logic are unit-tested.
    """
    import json

    object_id = 50100 if suffix == "generated" else 50101
    app_dir = work_root / f".bcbench-query-{suffix}"
    if app_dir.exists():
        remove_tree(app_dir)

    app_name = f"BC-Bench Query {suffix}"
    app_publisher = "BC-Bench"
    bootstrap_app_json(app_dir, app_name, version, id_range=(object_id, object_id), publisher=app_publisher)
    (app_dir / "query.al").write_text(wrap_query_as_api(query_text, object_id), encoding="utf-8")
    # Symbols are downloaded into an explicit .alpackages folder by Invoke-AppBuildAndPublish (below).

    result_file = app_dir / "result.json"
    app_utils_path = _config.paths.ps_script_path / "AppUtils.psm1"
    ps_script = _QUERY_RUN_TEMPLATE.substitute(
        app_utils_path=escape_ps_string(str(app_utils_path)),
        suffix=suffix,
        container_name=escape_ps_string(container.name),
        username=escape_ps_string(container.username),
        password=escape_ps_string(container.password),
        app_dir=escape_ps_string(str(app_dir)),
        app_name=escape_ps_string(app_name),
        app_publisher=escape_ps_string(app_publisher),
        publisher=_QUERY_API_PUBLISHER,
        group=_QUERY_API_GROUP,
        version=_QUERY_API_VERSION,
        entity_set=_entity_set_name(object_id),
        result_file=escape_ps_string(str(result_file)),
        company=escape_ps_string(company),
    )

    try:
        subprocess.run(
            ["pwsh", "-NoProfile", "-NonInteractive", "-Command", ps_script],
            cwd=work_root,
            capture_output=True,
            check=True,
            text=True,
            timeout=_config.timeout.execute_query,
        )
    except subprocess.CalledProcessError as e:
        logger.debug(f"Query compile/publish/fetch failed ({suffix}): {e.stdout}\n{e.stderr}")
        raise BuildError(f"query-{suffix}", (e.stdout or "") + (e.stderr or "")) from None
    except subprocess.TimeoutExpired:
        raise BuildTimeoutExpired(f"query-{suffix}", _config.timeout.execute_query) from None

    rows = json.loads(result_file.read_text(encoding="utf-8-sig") or "[]")
    return rows if isinstance(rows, list) else [rows]
