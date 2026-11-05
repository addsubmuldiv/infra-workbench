"""Offline feature smoke checks for the shipped runtime, using synthetic data only."""
from pathlib import Path
import ssl
import sys
from zoneinfo import ZoneInfo


def check_resources():
    import certifi
    from PIL import Image
    from .chat_tools import remote_source
    from .floating_theme import palettes
    from .server_import import import_template, parse_workbook

    checks = []
    context = ssl.create_default_context(cafile=certifi.where())
    if not context.get_ca_certs():
        raise RuntimeError('Bundled TLS certificate store is empty')
    checks.append('tls_certificates')
    for name in ('UTC', 'Asia/Shanghai', 'America/New_York'):
        ZoneInfo(name)
    checks.append('timezones')
    if not parse_workbook(import_template()):
        raise RuntimeError('Excel template round trip failed')
    checks.append('excel')
    root = Path(__file__).parent
    for source in root.glob('*.py'):
        compile(source.read_text(encoding='utf-8'), source.name, 'exec')
    compile(remote_source(), 'combined-remote-probe', 'exec')
    checks.append('remote_sources')
    if not palettes():
        raise RuntimeError('Floating monitor themes missing')
    for name in ('workbench.ico', 'workbench.png'):
        with Image.open(root/'assets'/name) as picture:
            picture.load()
    checks.append('desktop_assets')
    if sys.platform == 'win32':
        import tkinter as tk
        from PIL import ImageTk
        window = tk.Tk()
        window.withdraw()
        try:
            image = ImageTk.PhotoImage(Image.new('RGBA', (4, 4)), master=window)
            if image.width() != 4:
                raise RuntimeError('Tk image bridge failed')
            window.update_idletasks()
        finally:
            window.destroy()
        checks.append('tk_images')
    return checks


async def check_ssh(directory):
    """Real SSH/SFTP handshakes on loopback; never read user SSH config or agent."""
    import asyncssh

    password = 'synthetic-runtime-check'
    client_key = asyncssh.generate_private_key('ssh-ed25519')
    # Exercise encrypted OpenSSH key serialization as used by imported keys.
    client_key = asyncssh.import_private_key(client_key.export_private_key(
        'openssh', passphrase=password), passphrase=password)

    class Server(asyncssh.SSHServer):
        def begin_auth(self, username):
            return True

        def password_auth_supported(self):
            return True

        def validate_password(self, username, value):
            return username == 'runtime-check' and value == password

        def public_key_auth_supported(self):
            return True

        def validate_public_key(self, username, key):
            return username == 'runtime-check' and key == client_key.convert_to_public()

    async def process(request):
        request.stdout.write('IWB_SSH_OK')
        request.exit(0)

    host_key = asyncssh.generate_private_key('ssh-ed25519')
    known_hosts = directory/'known_hosts'
    server = await asyncssh.create_server(
        Server, '127.0.0.1', 0, server_host_keys=[host_key], process_factory=process,
        sftp_factory=lambda channel: asyncssh.SFTPServer(channel, chroot=str(directory)))
    try:
        port = server.get_port()
        known_hosts.write_bytes(b'[127.0.0.1]:'+str(port).encode()+b' '+host_key.export_public_key())
        common = dict(host='127.0.0.1', port=port, username='runtime-check',
                      known_hosts=str(known_hosts), config=None, agent_path=None)
        checks = []
        for name, authentication in (
            ('ssh_password', dict(password=password, client_keys=[], preferred_auth='password')),
            ('ssh_key', dict(client_keys=[client_key], preferred_auth='publickey')),
        ):
            async with asyncssh.connect(**common, **authentication) as connection:
                done = await connection.run('runtime-check', check=True)
                if done.stdout != 'IWB_SSH_OK':
                    raise RuntimeError('SSH command round trip failed')
                checks.append(name)
                if name == 'ssh_password':
                    async with connection.start_sftp_client() as sftp:
                        async with sftp.open('/round-trip.txt', 'w') as remote:
                            await remote.write('安装包 SFTP check')
                        async with sftp.open('/round-trip.txt', 'r') as remote:
                            if await remote.read() != '安装包 SFTP check':
                                raise RuntimeError('SFTP round trip failed')
                    checks.append('sftp')
        return checks
    finally:
        server.close()
        await server.wait_closed()


async def check_agent():
    from deepagents import create_deep_agent
    from deepagents.backends import StateBackend
    from langchain_core.messages import HumanMessage
    from langgraph.checkpoint.memory import InMemorySaver
    from langsmith import tracing_context
    from .agent_langchain import WorkbenchChatModel
    from .agent_runtime import bundled_files

    class Provider:
        async def turn(self, instructions, messages, tools, **kwargs):
            return {'message': {'content': 'IWB_AGENT_OK'}}

    graph = create_deep_agent(model=WorkbenchChatModel(Provider()),
                              backend=StateBackend(), skills=['/skills/'],
                              checkpointer=InMemorySaver())
    with tracing_context(enabled=False):
        result = await graph.ainvoke(
            {'messages': [HumanMessage(content='runtime-check')], 'files': bundled_files()},
            {'configurable': {'thread_id': 'runtime-check'}})
    if result['messages'][-1].content != 'IWB_AGENT_OK':
        raise RuntimeError('Assistant graph round trip failed')
    return ['agent_graph']
