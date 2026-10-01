from bcbench_core.operations import BusinessCentralSettings

from bcbench.config import Config


def create_business_central_settings(config: Config) -> BusinessCentralSettings:
    return BusinessCentralSettings(
        artifacts_cache=config.paths.bc_artifacts_cache,
        scripts_dir=config.paths.ps_script_path,
        build_baseapp_timeout=config.timeout.build_baseapp,
        build_app_timeout=config.timeout.build_app,
        test_timeout=config.timeout.test_execution,
        query_timeout=config.timeout.execute_query,
        alpackages_dirname=config.file_patterns.alpackages_dirname,
    )
