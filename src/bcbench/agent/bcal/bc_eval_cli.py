"""Run bc-eval with BC-Bench's fail-closed LLM API routing compatibility."""

from bcbench.agent.bcal.bc_eval_llm_api_bridge import install_sticky_route_compat


def main() -> None:
    install_sticky_route_compat()

    from bc_eval.cli import cli

    cli()


if __name__ == "__main__":
    main()
