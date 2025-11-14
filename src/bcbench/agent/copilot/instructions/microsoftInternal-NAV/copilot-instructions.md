# Dynamics 365 Business Central (AL) Development

This is a Business Central AL development environment for creating and extending Dynamics 365 Business Central applications. Learn more about Business Central: https://www.microsoft.com/en-gb/dynamics-365/products/business-central

## Key Context
Business Central is Microsoft's cloud ERP (Enterprise Resource Planning) solution for small and medium-sized businesses, covering finance, supply chain, sales, service, projects, and operations. It is extended and customized through AL extensions packaged as apps.
- Primary language: AL (Application Language for Business Central)
- Extension model: modular AL apps with `app.json` metadata
- Development patterns: event-driven extensibility, per-tenant and AppSource distribution
- Build & deploy: VS Code AL extension + CI/CD workflows (e.g., AL-Go) producing signed `.app` artifacts
- Configuration: `app.json` defines ID, name, version, dependencies, capabilities

## Coding Patterns
- Prefer modular, testable components
- Follow AL coding guidelines and best practices

### Code Quality
- Use meaningful object and variable names
- Keep procedures focused and single-purpose
- Document complex business logic
- Follow proper error handling patterns
