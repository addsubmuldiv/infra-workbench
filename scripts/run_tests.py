"""Run explicit functional test groups with the project virtualenv Python."""
import argparse
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def files(directory, names, suffix):
    return [f'{directory}/{name}{suffix}' for name in names.split()]


def group(backend='', frontend='', tooling=''):
    return (files('tests', backend, '.py')
            + files('frontend/tests', frontend, '.test.mjs') + tooling.split())


# Explicit lists make additions/deletions visible to --check instead of silently
# classifying a new regression by a guessed filename prefix. Overlap is allowed.
GROUPS = {
    'core': group(
        'test_api test_auth test_store test_core test_platform_credentials test_macos_credentials test_sudo',
        'requests'),
    'monitoring': group(
        'test_collection_scheduling test_live_collection test_probe_cache test_probe_cache_remote '
        'test_probe_timeouts test_refresh_settings test_system_metrics test_resource_stats '
        'test_history_time_ranges test_find_hosts test_fleet_schedule test_fleet_roundtrips '
        'test_process_details test_command_probe test_agent_query test_infra_assistant',
        'overview host-usage resourceHistory stateChanges infraAssistant'),
    'hosts': group(
        'test_host_alias test_server_import test_server_import_aliases test_server_import_matching '
        'test_server_import_routes test_import_host_keys test_clusters test_cluster_integration',
        'host-alias host-list remove-host server-import server-import-panel clusters cluster-sidebar '
        'cluster-panel-history cluster-terminal-workspace'),
    'reservations': group(
        'test_reservations test_reservation_count test_reservation_edit test_group_reservations '
        'test_resource_planning_integration test_mail test_notifications test_desktop_delivery',
        'reservations reservation-panel groupReservations mailSettings notifications notification-center'),
    'ssh': group(
        'test_ssh_password_routes test_ssh_proxy test_ssh_timeouts test_ssh_tunnels '
        'test_port_forwarding test_jump_platforms test_connection_info test_vscode',
        'ssh-password tunnel-manager vscode'),
    'terminal': group(
        'test_terminal test_terminal_posix test_terminal_workspace test_terminal_completions test_command_tools',
        'terminal terminal-window terminal-commands terminal-context terminal-highlights '
        'terminal-images-archives terminal-input terminal-insert terminal-paths terminal-renderer '
        'terminal-suggestions terminal-templates terminal-assistant-bridge cluster-terminal-workspace'),
    'files': group(
        'test_files test_files_search test_file_ops test_file_transfers test_folder_download '
        'test_folder_upload test_transfer_session_restore test_log_routes test_log_compare test_log_download',
        'files file-browser file-editor file-transfers file-window folder-upload text-editor-actions '
        'logDownload precision-sync'),
    'assistant': group(
        'test_agent_api test_agent_profiles test_agent_context test_agent_memory test_agent_chat '
        'test_assistant_efficiency test_assistant_performance test_chat_stream test_compaction_accounting test_deepagents '
        'test_model_stream test_model_turn test_codex_agent test_external_agents test_user_skills '
        'test_skill_integration test_unified_mcp test_mcp_output_budget test_mcp_query_economy',
        'agentChat agentChatStreaming agentSettings assistant-chat-streaming assistant-engine-picker '
        'chat-model-picker chat-reply-time chatMarkdown context-usage-meter modelCache skillMention '
        'skills skills-settings toolPresentation terminal-assistant-bridge'),
    'mcp': group(
        'test_agent_tools test_atomic_mcp test_mcp test_mcp_e2e test_unified_mcp '
        'test_mcp_output_budget test_mcp_query_economy test_skill_integration',
        'toolPresentation'),
    'workspace': group(
        'test_workspace_state test_interface_language',
        'workspace-state preferences browser-id navigation settings-navigation sidebar-layout '
        'window-layers assistant-window app-confirm locale first-run-guide demo-runtime demo-workspace'),
    'desktop': group(
        'test_desktop test_desktop_macos test_desktop_runtime test_desktop_startup test_desktop_update '
        'test_launcher test_quick_window test_floating_monitor test_floating_position '
        'test_floating_resize test_floating_context_menu test_macos_regressions test_startup_performance',
        'desktop-startup desktopUpdates latestUpdate native-window-command'),
    'distribution': group(
        'test_audit_release test_build_environment test_desktop_packaging test_installer_cleanup '
        'test_macos_install test_source_archive test_windows_launcher_install test_desktop_runtime',
        'buildInventory',
        'desktop/release.test.mjs scripts/sync-version.test.mjs'),
    'policy': group(
        'test_internal_defaults test_internal_defaults_review',
        'internal-defaults',
        'scripts/generate-internal-defaults.test.mjs scripts/test_test_groups.py'),
}


def inventory(root=ROOT):
    return {p.relative_to(root).as_posix()
            for directory, pattern in [('tests', 'test_*.py'), ('frontend/tests', '*.test.mjs'),
                                       ('scripts', 'test_*.py'), ('scripts', '*.test.mjs'),
                                       ('desktop', '*.test.mjs')]
            for p in (root / directory).glob(pattern)}


def validate(root=ROOT, groups=None):
    groups = GROUPS if groups is None else groups
    assigned = {path for paths in groups.values() for path in paths}
    actual = inventory(root)
    errors = []
    if actual - assigned:
        errors.append('Unassigned tests: ' + ', '.join(sorted(actual - assigned)))
    if assigned - actual:
        errors.append('Missing tests: ' + ', '.join(sorted(assigned - actual)))
    if errors:
        raise ValueError('\n'.join(errors))


def select(names):
    unknown = set(names) - GROUPS.keys()
    if unknown:
        raise ValueError('Unknown group: ' + ', '.join(sorted(unknown)))
    return sorted({path for name in names for path in GROUPS[name]})


def commands(paths, scope='all'):
    python_tests = [p for p in paths if p.endswith('.py') and scope in ('all', 'backend')]
    frontend = [p for p in paths if p.startswith('frontend/') and scope in ('all', 'frontend')]
    tooling = [p for p in paths if p.endswith('.mjs') and not p.startswith('frontend/')
               and scope in ('all', 'tooling')]
    result = []
    if python_tests:
        result.append([sys.executable, '-m', 'pytest', *python_tests, '-q'])
    if frontend or tooling:
        node = shutil.which('node') or 'node'
        result.append([node, 'scripts/generate-internal-defaults.mjs', '--check'])
        if frontend:
            result.append([node, '--test', *frontend])
        if tooling:
            result.append([node, '--test', *tooling])
    return result


def execute(planned):
    with tempfile.TemporaryDirectory(prefix='iwb-tests-') as data:
        env = dict(os.environ, IWB_DATA=data)
        for command in planned:
            print('+ ' + (subprocess.list2cmdline(command) if os.name == 'nt'
                          else shlex.join(command)), flush=True)
            result = subprocess.run(command, cwd=ROOT, env=env)
            if result.returncode:
                return result.returncode
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('groups', nargs='*', help='One or more names from --list')
    parser.add_argument('--list', action='store_true', help='List groups and file counts')
    parser.add_argument('--check', action='store_true', help='Check that every test is assigned')
    parser.add_argument('--all', action='store_true', help='Select all groups, including build tooling')
    parser.add_argument('--scope', choices=['all', 'backend', 'frontend', 'tooling'], default='all')
    parser.add_argument('--dry-run', action='store_true', help='Print selected files without running')
    args = parser.parse_args(argv)
    if args.all and args.groups:
        parser.error('Use group names or --all, not both')
    try:
        validate()
        if args.list:
            for name, paths in GROUPS.items():
                print(f'{name:15} {len(paths):3} files')
        if args.check:
            print(f'OK: {len(inventory())} test files assigned')
        if not args.all and not args.groups:
            if args.list or args.check:
                return 0
            parser.error('Choose group names, --list or --all')
        paths = select(list(GROUPS) if args.all else args.groups)
        planned = commands(paths, args.scope)
        if not planned:
            parser.error('No tests selected for this scope')
        if args.dry_run:
            for command in planned:
                print(subprocess.list2cmdline(command) if os.name == 'nt' else shlex.join(command))
            return 0
        return execute(planned)
    except (ValueError, OSError) as error:
        parser.exit(2, str(error) + '\n')


if __name__ == '__main__':
    sys.exit(main())
