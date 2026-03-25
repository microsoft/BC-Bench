---
layout: default
title: BC-Bench
---

A benchmark for evaluating AI coding agents on real-world **Business Central (AL)** development tasks, inspired by [SWE-Bench](https://github.com/swe-bench/SWE-bench).

## Categories

| Category | Description |
|----------|-------------|
| [Bug Fixing](bug-fix.md) | Follows [SWE-Bench](https://www.swebench.com/) methodology to evaluate bug fixing in AL code |
| [Test Generation](test-generation.md) | "Reverses" SWE-Bench: Generates reproduction tests (TDD) instead of fixes |
| Code Review | *Coming Soon* |

## What is Business Central?

**Microsoft Dynamics 365 Business Central** is a comprehensive business management solution for small and medium-sized organizations. It connects sales, service, finance, and operations to help businesses work smarter, adapt faster, and perform better.

**AL (Application Language)** is the programming language used to develop extensions and customizations for Business Central. It is a domain-specific language designed for building business applications for the Business Central platform.

## Why BC-Bench?

- **Evaluate real-world ERP development** — Tasks are derived from actual Business Central issues and pull requests
- **AL is a low-resource, domain-specific programming language** — AL has limited public training data, tooling, and community examples compared to mainstream languages (e.g., Python), making BC-Bench better suited for evaluating different agent and system setups in in a realistic AL development setting.
- **Enable rapid iteration** — Help engineers select models and iterate on MCP servers, custom instructions, and agent setups in a realistic but controllable environment.
