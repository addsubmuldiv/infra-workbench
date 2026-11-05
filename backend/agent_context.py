"""Read model capacity only from the configured provider's exact model metadata."""
from .internal_defaults import ASSISTANT_CONTEXT_FALLBACK_TOKENS, ASSISTANT_METADATA_TIMEOUT_SECONDS, ASSISTANT_METADATA_SUCCESS_CACHE_SECONDS, ASSISTANT_METADATA_FAILURE_CACHE_SECONDS
from urllib.parse import quote, urlsplit
import asyncio
import hashlib
import time

FALLBACK_CONTEXT = ASSISTANT_CONTEXT_FALLBACK_TOKENS
_CONTEXT_FIELDS = ('context_length', 'context_window', 'max_model_len', 'max_context_length', 'max_input_tokens', 'input_token_limit')
_METADATA_RECORDS = ('top_provider', 'limits', 'capabilities', 'model_info', 'metadata')
_IDENTITY_FIELDS = ('id', 'slug', 'model', 'name', 'model_name')
# Exact API model specifications checked 2026-11-05. These are context windows,
# not the separately documented 128,000 maximum output tokens.
# https://developers.openai.com/api/docs/models/gpt-6.1-terra
_OFFICIAL_OPENAI_CONTEXT = {'gpt-6.1-terra': 1050000}


def _official_capacity(config):
    endpoint = urlsplit(config['base_url'])
    if (endpoint.scheme == 'https' and endpoint.netloc == 'api.openai.com'
            and endpoint.path.rstrip('/') == '/v1' and not endpoint.query and not endpoint.fragment):
        return _OFFICIAL_OPENAI_CONTEXT.get(config['model'])
    return None


def model_capacity(item):
    if not isinstance(item, dict):
        return None
    candidates = []
    pending = [item]
    seen = set()
    while pending:
        record = pending.pop()
        if id(record) in seen:
            continue
        seen.add(id(record))
        for key in _CONTEXT_FIELDS:
            value = record.get(key)
            if isinstance(value, int) and not isinstance(value, bool) and 4096 <= value <= 20000000:
                candidates.append(value)
        # Traverse known metadata containers only. In particular, max_tokens and
        # generation parameters are output budgets, not context capacities.
        pending.extend(record[key] for key in _METADATA_RECORDS if isinstance(record.get(key), dict))
    return min(candidates) if candidates else None


def _metadata_capacity(data, model):
    """Accept list/detail envelopes, retaining the public alias as the identity."""
    pending = [data]
    capacities = []
    while pending:
        item = pending.pop()
        if isinstance(item, list):
            pending.extend(item)
        elif isinstance(item, dict):
            identities = [item[field] for field in _IDENTITY_FIELDS if isinstance(item.get(field), str)]
            if identities:
                if model in identities:
                    value = model_capacity(item)
                    if value is not None:
                        capacities.append(value)
                # Never match litellm_params.model: an upstream name belonging
                # to a different public alias does not establish its capacity.
                continue
            pending.extend(item[key] for key in ('data', 'models') if isinstance(item.get(key), (dict, list)))
    # A router alias can have multiple deployments. Respect the smallest
    # declared capacity so an arbitrary listing order cannot overstate it.
    return min(capacities) if capacities else None


async def resolve_context(service, *, refresh=False):
    # Share the settings lock so a switch cannot pair old metadata with a new model.
    async with service.lock:
        config = dict(service.config)
        manual = config.get('context_window')
        if manual:
            return dict(tokens=manual, source='manual', trigger_tokens=int(manual * .85))
        key = service.key_for(config)
        identity = (config['base_url'], config['model'], config.get('protocol'), hashlib.sha256(key.encode()).hexdigest())
        cached = getattr(service, '_context_cache', None)
        if not refresh and cached and cached[0] == identity and time.monotonic() < cached[1]:
            return dict(cached[2])
        tokens = None
        if config['model']:
            try:
                # One deadline bounds all metadata requests. An unsupported
                # endpoint must not prevent trying another metadata endpoint.
                async with asyncio.timeout(ASSISTANT_METADATA_TIMEOUT_SECONDS):
                    for path in ('/models', '/models/' + quote(config['model'], safe=''), '/model/info'):
                        try:
                            data = await service.request(config, key, path)
                        except ValueError:
                            continue
                        tokens = _metadata_capacity(data, config['model'])
                        if tokens is not None:
                            break
            except TimeoutError:
                pass
        source = 'provider' if tokens else 'fallback'
        if tokens is None:
            tokens = _official_capacity(config)
            if tokens is not None:
                source = 'official'
        result = dict(tokens=tokens or FALLBACK_CONTEXT, source=source,
                      trigger_tokens=int((tokens or FALLBACK_CONTEXT) * .85))
        service._context_cache = (identity, time.monotonic() + (ASSISTANT_METADATA_SUCCESS_CACHE_SECONDS if tokens else ASSISTANT_METADATA_FAILURE_CACHE_SECONDS), result)
        return dict(result)
