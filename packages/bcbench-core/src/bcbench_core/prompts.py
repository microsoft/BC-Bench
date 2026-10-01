from collections.abc import Mapping

from jinja2.sandbox import SandboxedEnvironment

_jinja = SandboxedEnvironment(autoescape=False)


def render_prompt(template: str, context: Mapping[str, object]) -> str:
    return _jinja.from_string(template).render(context)
