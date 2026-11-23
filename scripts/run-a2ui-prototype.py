"""Start the workbench A2UI prototype on loopback in a new temporary workspace."""

import argparse
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def read_model_settings(database, profile_name):
    uri = database.resolve().as_uri() + '?mode=ro'
    with closing(sqlite3.connect(uri, uri=True)) as source:
        preferences = {
            key: json.loads(value) for key, value in source.execute(
                "SELECT id,value FROM config WHERE id IN ('agent_api_profiles','agent_api_settings')")
        }
    if collection := preferences.get('agent_api_profiles'):
        active = collection['active_id']
        if profile_name:
            active = next(key for key, profile in collection['profiles'].items() if profile['name'] == profile_name)
        return collection['profiles'][active]['config'], ('provider' if active == 'legacy' else 'provider'+active)
    if profile_name:
        raise ValueError('No named model profiles in the source database.')
    return preferences['agent_api_settings'], 'provider'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-db', required=True, type=Path, help='Read only the active model settings from this database.')
    parser.add_argument('--profile', help='Use this saved model profile instead of the active one.')
    parser.add_argument('--port', default=8786, type=int)
    args = parser.parse_args()
    if not (ROOT/'frontend'/'dist'/'index.html').is_file():
        parser.error('Build the workbench frontend first.')

    sys.path.insert(0, str(ROOT))
    try:
        config, slot = read_model_settings(args.source_db, args.profile)
    except (KeyError, StopIteration, ValueError, sqlite3.Error):
        parser.error('Could not read the requested model profile from the source database.')
    with tempfile.TemporaryDirectory(prefix='iwb-a2ui-') as data:
        os.environ['IWB_DATA'] = data
        from backend.agent_api import AgentAPISettings, credential_identity
        from backend.app import app as default_app, create_app
        from backend.credentials import UnsupportedCredentialStore, create_credential_store
        import uvicorn

        settings = AgentAPISettings.model_validate(config).model_dump(exclude={'api_key','remember','profile_id'})
        if not settings['model']:
            parser.error('The selected workbench profile has no model.')
        credential = create_credential_store('InfraWorkbench/agent/').get(slot)
        if credential and credential.get('identity') != credential_identity(settings):
            parser.error('The saved credential does not match the model provider.')
        default_app.state.agent_chat.store.db.close()
        app = create_app(start_poll=False, agent_credential_store=UnsupportedCredentialStore())
        provider = app.state.agent_api
        provider.persist(config=settings)
        provider.config = settings
        provider.memory = credential
        app.state.agent_chat.a2ui_prototype = True
        # Refuse host connection and other writes unrelated to the chat in this instance.
        @app.middleware('http')
        async def prototype_writes(request, call_next):
            path = request.url.path
            if request.method in ('GET', 'HEAD') or path.startswith(('/api/assistant/chats', '/api/workspace')):
                return await call_next(request)
            from fastapi.responses import JSONResponse
            return JSONResponse({'detail':'A2UI prototype: only chat and workspace preferences can change.'}, status_code=403)

        print(f'A2UI prototype: http://127.0.0.1:{args.port}/', flush=True)
        uvicorn.run(app, host='127.0.0.1', port=args.port, access_log=False)


if __name__ == '__main__':
    main()
