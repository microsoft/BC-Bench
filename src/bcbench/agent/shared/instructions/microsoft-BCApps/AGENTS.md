# Dynamics 365 Business Central (AL) Development

Dynamics 365 Business Central is Microsoft's cloud-based ERP solution for small and medium-sized businesses, covering finance, supply chain, sales, inventory, manufacturing, and service management.

**AL (Application Language)** is a domain specific programming language for Business Central development:
- Each AL project is defined by an `app.json` file at its root folder
- Apps are compiled into `.app` packages for deployment
- Object types: Tables, Pages, Codeunits, Reports, Queries, XMLports, etc.
- Extensibility through events and object (table/page/enum) extensions

## Reviewing AL code changes

When you review AL code changes, evaluate the diff against every one of the following
domain checklists. Read each file under `.github/instructions/` and apply its guidance:

- `.github/instructions/security.md` — security
- `.github/instructions/performance.md` — performance
- `.github/instructions/privacy.md` — privacy and data protection
- `.github/instructions/style.md` — AL style and conventions
- `.github/instructions/accessibility.md` — accessibility
- `.github/instructions/upgrade.md` — upgrade and data-migration safety

Only raise findings that are supported by one of these checklists. For each finding,
cite the concrete rule it violates and point to the exact file and line in the diff.
