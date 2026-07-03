# Security Policy

Metronix Memory is open-source, self-hosted AI memory infrastructure. Security reports are welcome and should be handled privately so maintainers can validate and fix issues before public disclosure.

## Reporting a Vulnerability

Please do not open a public issue, discussion, pull request, or chat message for a suspected vulnerability.

Report privately using one of these channels:

- Email: `ariel@mtrnix.com`
- GitHub private vulnerability reporting: https://github.com/mtrnix/metronix-memory/security/advisories/new

Include as much of the following as you can:

- A clear description of the issue and affected component
- Steps to reproduce, including configuration, inputs, or requests
- Affected version, release tag, commit hash, or Docker image tag
- Impact assessment, such as data exposure, authentication bypass, privilege escalation, remote code execution, or denial of service
- Proof-of-concept details, logs, screenshots, or sample requests, if available
- Whether you want public credit after disclosure

Please avoid accessing, modifying, deleting, or exfiltrating data that is not yours. If you discover sensitive information during testing, stop and include the minimum detail needed for us to validate the issue.

## Response Targets

We aim to respond quickly, but exact timing can vary with severity and maintainer availability.

| Phase | Target |
| --- | --- |
| Acknowledge report | Within 2 business days |
| Initial triage | Within 5 business days |
| Confirmed critical fix | As soon as practical, with priority handling |
| Confirmed high or moderate fix | In the next appropriate security release |
| Public advisory | After a fix or mitigation is available |

If a report is incomplete, we may ask for more information before assigning severity or committing to a fix timeline.

## Coordinated Disclosure

We follow coordinated disclosure:

1. The reporter submits the vulnerability privately.
2. Maintainers validate scope, impact, and severity.
3. A fix, workaround, or mitigation is prepared.
4. A release or advisory is published once users have a practical path to protect themselves.
5. The reporter is credited if they request credit and disclosure terms allow it.

Please give maintainers a reasonable opportunity to resolve confirmed vulnerabilities before publishing details.

## Supported Versions

Security fixes are applied to the actively maintained code line.

| Version | Security support |
| --- | --- |
| `main` | Supported; fixes land here first |
| Latest published release | Supported when a release exists and a backport is practical |
| Older releases, forks, and modified deployments | Not supported; upgrade to a maintained version |

## Scope

In scope:

- API server, OpenAI-compatible API, and MCP endpoints
- Authentication, authorization, sessions, JWT handling, API keys, and workspace isolation
- Ingestion, retrieval, memory, freshness, export, and connector orchestration code in this repository
- Secret handling, environment configuration, logging, and accidental sensitive-data exposure
- Container image, Docker Compose defaults, and deployment configuration provided by this repository
- Dependency vulnerabilities that are exploitable through Metronix Memory

Out of scope:

- Vulnerabilities in third-party services connected to Metronix Memory, such as Jira, Confluence, Slack, Discord, Telegram, model providers, vector databases, or graph databases
- User-managed infrastructure, reverse proxies, cloud accounts, databases, model endpoints, and MCP clients
- Public demo instances, test instances, or deployments not operated by the maintainers
- Social engineering, phishing, physical attacks, and spam
- Denial-of-service findings that rely only on excessive traffic volume or resource exhaustion without a distinct application flaw
- Reports from automated scanners without a demonstrated exploitable impact
- Disclosure of non-sensitive version banners, stack traces from local development mode, or missing optional hardening headers on non-browser API endpoints

## Security Best Practices for Deployers

Metronix Memory is intended to run in environments you control. Production deployments should be treated as sensitive infrastructure because they may process private documents, credentials, chat history, agent memory, and knowledge graphs.

- Put the API and MCP endpoints behind TLS and a trusted reverse proxy before exposing them beyond localhost or a private network.
- Set `METRONIX_AUTH_REQUIRED=true` in production and verify that all API clients authenticate as expected.
- Set a strong, unique `METRONIX_MCP_API_KEY`; rotate it if it is shared accidentally or checked into a client configuration.
- Change the default admin password before using a deployment with real data. `AUTH_PASSWORD` seeds `admin@metronix.local` only on first start when the users table is empty; update existing users through the user API or admin UI.
- Keep `.env`, backups, logs, exports, and database volumes out of source control and public object storage.
- Bind PostgreSQL, Redis, Qdrant, Neo4j, Ollama, and other backing services to private interfaces or Docker networks only.
- Use least-privilege credentials for external connectors and model providers.
- Review logs before sharing them; prompts, documents, headers, connector metadata, and model responses can contain sensitive data.
- Keep dependencies, containers, and base images updated, and review the repository's security scan workflow results when upgrading.
- Disable unused connectors and channels in production to reduce exposed credentials and attack surface.

## Maintainer Handling

Maintainers should treat private reports, proof-of-concept code, reporter identity, and vulnerability details as confidential until coordinated disclosure is complete. Security fixes should include tests where practical and should avoid revealing exploit details in public commit messages before an advisory is published.

## Public Acknowledgment

We are happy to credit reporters who follow this policy. Tell us how you would like to be named when you submit the report.
