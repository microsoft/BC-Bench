# Dynamics 365 Business Central (AL) Development

Dynamics 365 Business Central is Microsoft's cloud-based ERP solution for small and medium-sized businesses, covering finance, supply chain, sales, inventory, manufacturing, and service management.

**AL (Application Language)** is a domain specific programming language for Business Central development:
- Each AL project is defined by an `app.json` file at its root folder
- Apps are compiled into `.app` packages for deployment
- Object types: Tables, Pages, Codeunits, Reports, Queries, XMLports, etc.
- Extensibility through events and object (table/page/enum) extensions

## Project Structure

This repository contains Business Central applications in a layered architecture:

### System Application (`App/BCApps/src/System Application/`)
Foundational layer (git submodule) providing system-level utilities: user management, security, data handling (XML/JSON), REST client, Azure services, telemetry, and upgrade management. Each module is a separate app.

**Note:** This is developed in a different repository (BCApps) and included as a git submodule. Use for reference only - do not modify these files.

### Base Application (`App/Layers/W1/BaseApp/`)
Core monolithic application containing fundamental business logic: finance, sales, purchasing, inventory, warehouse, manufacturing, jobs, service management, and master data. Depends on System Application.

### First-Party Apps (`App/Apps/W1/`)
Modular extensions for add-on functionality: Shopify integration, email connectors, AI features, compliance (Intrastat, VAT), Power BI/Excel reports, APIs, and industry-specific features.

### Localizations: Multi-Country/Region Support
Business Central supports many countries and regions through a file-level inheritance model. This creates significant complexity as each country/region can have many localized files.

**Structure:**
- `App/Layers/[COUNTRY/REGION]/` - Country/region-specific layers
- `App/Apps/[COUNTRY/REGION]/` - Country/region-specific extensions
- **W1** = Worldwide (base), **US** = United States, **DE** = Germany, etc.

**Inheritance rules:**
- Files **only in W1** are used by all countries/regions
- Files in **both W1 and US**: US version takes precedence for US deployments
- Countries/regions can add many new objects for local requirements (e.g., tax reporting, regulatory compliance)
- Each localization may override dozens or hundreds of files from the base layer

**Example:** `App/Layers/W1/BaseApp/SalesInvoice.Page.al` is used globally, but `App/Layers/US/BaseApp/SalesInvoice.Page.al` overrides it for United States with local tax fields.

## Development Focus

**Important:** Unless explicitly specified otherwise, focus all development tasks on the **W1 (Worldwide)** layer. Country/region-specific changes should only be made when explicitly requested.
