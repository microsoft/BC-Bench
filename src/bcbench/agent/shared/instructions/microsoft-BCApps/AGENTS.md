# Dynamics 365 Business Central (AL) Development

Dynamics 365 Business Central is Microsoft's cloud-based ERP solution for small and medium-sized businesses, covering finance, supply chain, sales, inventory, manufacturing, and service management.

**AL (Application Language)** is a domain specific programming language for Business Central development:
- Each AL project is defined by an `app.json` file at its root folder
- Apps are compiled into `.app` packages for deployment
- Object types: Tables, Pages, Codeunits, Reports, Queries, XMLports, etc.
- Extensibility through events and object (table/page/enum) extensions

## Reviewing AL code

A `bcquality-al-review` skill is available through the `skill` tool. It reviews Business Central AL changes against BCQuality's curated, BC-specific quality rules. When your task is to review AL code (a diff or a file), use it to ground your findings.
