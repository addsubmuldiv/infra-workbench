"""Read model capacity only from the configured provider's exact model metadata."""
from urllib.parse import quote
import asyncio
import hashlib
import time

FALLBACK_CONTEXT = 32000

def model_capacity(item):
    if not isinstance(item, dict):
        return None
    candidates = []
    for record in (item, item.get('top_provider'), item.get('limits'), item.get('capabilities')):
        if not isinstance(record, dict):
            continue
        for key in ('context_length', 'context_window', 'max_model_len', 'max_context_length', 'max_input_tokens', 'input_token_limit'):
            value = record.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and 4096 <= value <= 20000000:
                candidates.append(value)
    return min(candidates) if candidates else None

async def resolve_context(service, *, refresh=False):
    # Share the settings lock so a switch cannot pair old metadata with a new model.
    async with service.lock:
        config = dict(service.config)
        manual = config.get('context_window')
        if manual:
            return dict(tokens=manual, source='manual', trigger_tokens=int(manual * .85))
        key = service.key_for(config)
        identity = (config['base_url'], config['model'], hashlib.sha256(key.encode()).hexdigest())
        cached = getattr(service, '_context_cache', None)
        if not refresh and cached and cached[0] == identity and time.monotonic() < cached[1]:
            return dict(cached[2])
        tokens = None
        if config['model']:
            try:
                # Metadata lookup must not consume the full model-response timeout.
                async with asyncio.timeout(8):
                    try:
                        data = await service.request(config, key, '/models')
                    except ValueError:
                        data = {}
                    envelope = data.get('data') if isinstance(data.get('data'), dict) else data
                    items = envelope.get('data', envelope.get('models', []))
                    for item in items if isinstance(items, list) else []:
                        if isinstance(item, dict) and any(item.get(field) == config['model'] for field in ('id', 'slug', 'model', 'name')):
                            tokens = model_capacity(item)
                            break
                    if tokens is None:
                        data = await service.request(config, key, '/models/' + quote(config['model'], safe=''))
                        item = data.get('data', data)
                        if isinstance(item, dict) and any(item.get(field) == config['model'] for field in ('id', 'slug', 'model', 'name')):
                            tokens = model_capacity(item)
            except (ValueError, TimeoutError):
                pass
        result = dict(tokens=tokens or FALLBACK_CONTEXT, source='provider' if tokens else 'fallback',
                      trigger_tokens=int((tokens or FALLBACK_CONTEXT) * .85))
        service._context_cache = (identity, time.monotonic() + (3600 if tokens else 60), result)
        return dict(result)
