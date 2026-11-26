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
        'core/test_api core/test_auth core/test_store core/test_core core/test_platform_credentials core/test_macos_credentials core/test_sudo',
        'core/requests'),
    'monitoring': group(
        'monitoring/test_collection_scheduling monitoring/test_live_collection monitoring/test_probe_cache monitoring/test_probe_cache_remote '
        'monitoring/test_probe_timeouts monitoring/test_refresh_settings monitoring/test_system_metrics monitoring/test_resource_stats '
        'monitoring/test_history_time_ranges monitoring/test_find_hosts monitoring/test_fleet_schedule monitoring/test_fleet_roundtrips '
        'monitoring/test_process_details monitoring/test_command_probe monitoring/test_agent_query monitoring/test_infra_assistant',
        'monitoring/overview monitoring/host-usage monitoring/resourceHistory monitoring/stateChanges monitoring/infraAssistant'),
    'hosts': group(
        'hosts/test_host_alias hosts/test_server_import hosts/test_server_import_aliases hosts/test_server_import_matching '
        'hosts/test_server_import_routes hosts/test_import_host_keys hosts/test_clusters hosts/test_cluster_integration',
        'hosts/host-alias hosts/host-list hosts/remove-host hosts/server-import hosts/server-import-panel hosts/clusters hosts/cluster-sidebar '
        'hosts/cluster-panel-history hosts/cluster-terminal-workspace'),
    'reservations': group(
        'reservations/test_reservations reservations/test_reservation_count reservations/test_reservation_edit reservations/test_group_reservations '
        'reservations/test_resource_planning_integration reservations/test_mail reservations/test_notifications reservations/test_desktop_delivery',
        'reservations/reservations reservations/reservation-panel reservations/groupReservations reservations/mailSettings reservations/notifications reservations/notification-center'),
    'ssh': group(
        'ssh/test_ssh_password_routes ssh/test_ssh_proxy ssh/test_ssh_timeouts ssh/test_ssh_tunnels '
        'ssh/test_port_forwarding ssh/test_jump_platforms ssh/test_connection_info ssh/test_vscode ssh/test_ssh_config_export',
        'ssh/ssh-password ssh/tunnel-manager ssh/vscode'),
    'terminal': group(
        'terminal/test_terminal terminal/test_terminal_posix terminal/test_terminal_workspace terminal/test_terminal_completions terminal/test_command_tools',
        'terminal/terminal terminal/terminal-window terminal/terminal-commands terminal/terminal-context terminal/terminal-highlights '
        'terminal/terminal-images-archives terminal/terminal-input terminal/terminal-insert terminal/terminal-paths terminal/terminal-renderer '
        'terminal/terminal-suggestions terminal/terminal-templates terminal/terminal-assistant-bridge hosts/cluster-terminal-workspace'),
    'files': group(
        'files/test_files files/test_files_search files/test_file_ops files/test_file_transfers files/test_folder_download '
        'files/test_folder_upload files/test_transfer_session_restore files/test_log_routes files/test_log_compare files/test_log_download',
        'files/files files/file-browser files/file-editor files/file-transfers files/file-window files/folder-upload files/file-drop files/text-editor-actions '
        'files/logDownload files/precision-sync'),
    'assistant': group(
        'assistant/test_agent_permission_integration assistant/test_agent_permissions assistant/test_agent_capabilities assistant/test_agent_external_mcp assistant/test_agent_api assistant/test_agent_profiles assistant/test_agent_context assistant/test_agent_memory assistant/test_agent_chat '
        'assistant/test_assistant_efficiency assistant/test_assistant_performance assistant/test_chat_stream assistant/test_compaction_accounting assistant/test_deepagents '
        'assistant/test_model_stream assistant/test_model_turn assistant/test_codex_agent assistant/test_codex_host assistant/test_external_agents assistant/test_antigravity_agent assistant/test_user_skills '
        'assistant/test_skill_integration assistant/test_unified_mcp assistant/test_mcp_output_budget assistant/test_mcp_query_economy',
        'assistant/agentChat assistant/agentChatStreaming assistant/agentSettings assistant/assistant-chat-streaming assistant/assistant-engine-picker '
        'assistant/chat-model-picker assistant/chat-reply-time assistant/chatMarkdown assistant/context-usage-meter assistant/modelCache assistant/skillMention assistant/codex-host '
        'assistant/skills assistant/skills-settings assistant/toolPresentation terminal/terminal-assistant-bridge'),
    'mcp': group(
        'assistant/test_agent_permission_integration assistant/test_agent_permissions assistant/test_agent_capabilities assistant/test_agent_external_mcp mcp/test_agent_tools mcp/test_atomic_mcp mcp/test_mcp mcp/test_mcp_e2e assistant/test_unified_mcp '
        'assistant/test_mcp_output_budget assistant/test_mcp_query_economy assistant/test_skill_integration mcp/test_workbench_feature_mcp',
        'assistant/toolPresentation'),
    'workspace': group(
        'workspace/test_workspace_state workspace/test_interface_language',
        'workspace/workspace-state workspace/preferences workspace/browser-id workspace/navigation workspace/settings-navigation workspace/sidebar-layout '
        'workspace/window-layers workspace/assistant-window workspace/app-confirm workspace/locale workspace/first-run-guide workspace/github-star-prompt workspace/demo-runtime workspace/demo-workspace'),
    'desktop': group(
        'desktop/test_desktop desktop/test_desktop_macos desktop/test_desktop_runtime desktop/test_desktop_startup desktop/test_desktop_update '
        'desktop/test_launcher desktop/test_quick_window desktop/test_floating_monitor desktop/test_floating_position '
        'desktop/test_floating_resize desktop/test_floating_context_menu desktop/test_macos_regressions desktop/test_startup_performance',
        'desktop/desktop-startup desktop/desktopUpdates desktop/latestUpdate desktop/native-window-command'),
    'distribution': group(
        'distribution/test_audit_release distribution/test_build_environment distribution/test_desktop_packaging distribution/test_installer_cleanup '
        'distribution/test_macos_install distribution/test_source_archive distribution/test_windows_launcher_install desktop/test_desktop_runtime',
        'distribution/buildInventory',
        'desktop/release.test.mjs scripts/sync-version.test.mjs'),
    'policy': group(
        'policy/test_internal_defaults policy/test_internal_defaults_review',
        'policy/internal-defaults',
        'scripts/generate-internal-defaults.test.mjs scripts/test_test_groups.py'),
}


def inventory(root=ROOT):
    return {p.relative_to(root).as_posix()
            for directory, pattern in [('tests', '**/test_*.py'), ('frontend/tests', '**/*.test.mjs'),
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
