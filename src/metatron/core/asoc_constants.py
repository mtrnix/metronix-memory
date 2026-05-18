"""ASOC-related constants shared between core/config.py (L0) and integrations/ (L3).

This tiny module exists to avoid an L0→L3 import cycle: config.py needs the
default tool whitelist for its ``asoc_mcp_allowed_tools`` field default, but the
primary home of ``AsocMcpClient`` is L3 (integrations/).

Rule: only string constants here — zero business logic, zero upward imports.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Default MCP read-only tool whitelist (37 names, per Confluence §3 / MTRNIX-356)
# ---------------------------------------------------------------------------
# Write tools (e.g. asoc_start_scan, asoc_update_issue) are intentionally absent.
# Any env-override via METATRON_ASOC_MCP_ALLOWED_TOOLS must still pass the
# Settings.asoc_mcp_allowed_tools validator (names must start with "asoc_").

ASOC_MCP_READ_ONLY_TOOLS_DEFAULT: frozenset[str] = frozenset(
    {
        "asoc_list_issues",
        "asoc_get_issue",
        "asoc_count_issues",
        "asoc_list_issue_statuses",
        "asoc_get_issue_available_transitions",
        "asoc_get_issue_comments",
        "asoc_get_issue_history",
        "asoc_get_issues_categories",
        "asoc_get_issues_filters",
        "asoc_list_projects",
        "asoc_get_project",
        "asoc_get_project_layer_tree",
        "asoc_list_layers",
        "asoc_get_layer",
        "asoc_list_scan_results",
        "asoc_get_scan_stats",
        "asoc_compare_scan_results",
        "asoc_list_security_checks",
        "asoc_get_security_check",
        "asoc_get_stats_all",
        "asoc_get_stats_severity",
        "asoc_get_stats_by_tool",
        "asoc_get_stats_projects",
        "asoc_get_integral_risk",
        "asoc_get_defect_time",
        "asoc_list_sboms",
        "asoc_list_dependencies",
        "asoc_get_dependency",
        "asoc_list_trackers",
        "asoc_get_tracker_task_types",
        "asoc_list_users",
        "asoc_list_groups",
        "asoc_get_profile",
        "asoc_list_quality_gates",
        "asoc_get_layer_gates",
        "asoc_list_events",
        "asoc_get_copilot_fp_analysis",
    }
)
