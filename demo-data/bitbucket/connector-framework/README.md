# connector-framework

## Overview

The connector-framework repository implements the core infrastructure for the MOD-A Connector Framework module within the Amisol DataPlatform Demo. This framework provides a unified abstraction layer for integrating external data sources, handling authentication, data transformation, and error recovery patterns.

This repository specifically delivers features F-A1 (connector registration and lifecycle management), F-A2 (generic OAuth2/OAuth1 authentication handler), and F-A3 (configurable retry and circuit breaker patterns). These capabilities enable rapid development of new source connectors while maintaining consistent operational behavior across all integrations.

## Configuration

| Environment Variable | Description | Default |
|---------------------|-------------|---------|
| `METATRON_API_ENDPOINT` | URL of the Metatron API for catalog integration | `http://metatron:8080` |
| `METATRON_API_KEY` | Authentication token for Metatron API access | (required) |
| `AMISOL_DPLAT_LOG_LEVEL` | Logging verbosity (DEBUG, INFO, WARN, ERROR) | `INFO` |
| `AMISOL_DPLAT_CONNECTION_POOL_SIZE` | Maximum database connections per connector | `10` |

## Related

- JIRA: DPLAT-EPIC-01, DPLAT-EPIC-02, DPLAT-EPIC-03, DPLAT-001, DPLAT-002
- Confluence: DPLAT/02-connector-framework-overview, DPLAT/04-salesforce-connector-business-rules, DPLAT/06-connector-config-api

## Local development

Run the framework locally with `docker-compose up --build`. Execute tests using `pytest tests/ -v` and lint code with `make lint`. For development debugging, set `AMISOL_DPLAT_LOG_LEVEL=DEBUG` and connect to the exposed debug port (5678).