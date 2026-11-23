"""Validate model-generated A2UI and resolve table/chart data from query results."""

import json
import re


CATALOG_ID = 'urn:infra-workbench:a2ui-prototype'

LAYOUT_INSTRUCTIONS = '''Respond in the user's language with a concise answer in plain text. When a visual answer adds value,
append one JSON array of components between <a2ui-json> and </a2ui-json> tags. The tags and array
are for the renderer, so omit the surrounding Markdown code fence. A short reply can be text only.
Choose the components, order, row selection and arrangement yourself to answer the user's specific question.
Use these allowed component shapes (all fields required except rows and variant):
- {"id":"root","component":"Column","children":["another_id"]} stacks components vertically.
- {"id":"group","component":"Row","children":["first","second"]} groups items side by side where space allows.
- {"id":"note","component":"Text","text":"plain text","variant":"heading"} (variant: heading or body).
- {"id":"table","component":"DataTable","title":"...","dataset":"hosts","rows":["EXACT_HOST_ROW_ID"],
   "columns":[{"field":"id","label":"Machine"},{"field":"idle","label":"Idle devices"}]}.
- {"id":"chart","component":"BarChart","title":"...","dataset":"devices","rows":["EXACT_DEVICE_ROW_ID"],
   "labelField":"id","valueField":"used_gib"}.
These are individual component examples. Combine, omit, nest or reorder components as appropriate.
Exactly one component must have id "root" when present. The component ids must be unique ASCII identifiers.
Keep the surface compact, with at most 12 components and 6 table columns. Each child has one parent.
Dataset must be hosts, devices or processes. Rows are exact ids from the chosen dataset in display order;
omitting rows shows all records in that dataset. Chart values and table cells are bound by the application.
Use dataset fields exactly as written. Chart valueField must be numeric (null if unknown).
The renderer uses GiB for memory fields and displays counts without a unit.
Explain the result in text even when you also provide a surface. Do not repeat every table row in prose.
'''


def bounded_text(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('invalid text')
    return value.strip()


def component_data(component, datasets):
    kind = component['component']
    if kind in ('Column', 'Row'):
        children = component['children']
        if not isinstance(children, list) or not children or len(children) > 8:
            raise ValueError('invalid layout children')
        return dict(children=children)
    if kind == 'Text':
        variant = component.get('variant', 'body')
        if variant not in ('body', 'heading'):
            raise ValueError('invalid text variant')
        return dict(text=bounded_text(component['text']), variant=variant)
    if kind not in ('DataTable', 'BarChart'):
        raise ValueError('unknown component')

    source = datasets[component['dataset']]
    records = {row['id']: row for row in source}
    row_ids = component.get('rows', list(records))
    if not isinstance(row_ids, list) or not row_ids or len(set(row_ids)) != len(row_ids):
        raise ValueError('invalid row selection')
    rows = [records[row_id] for row_id in row_ids]
    title = bounded_text(component['title'])
    if kind == 'DataTable':
        columns = component['columns']
        if not isinstance(columns, list) or not 1 <= len(columns) <= 6:
            raise ValueError('invalid table columns')
        return dict(title=title, columns=[bounded_text(column['label'], 50) for column in columns],
                    rows=[[row[column['field']] for column in columns] for row in rows])
    field = component['valueField']
    values = [row[field] for row in rows]
    if any(value is not None and type(value) not in (int, float) for value in values):
        raise ValueError('chart field must be numeric')
    labels = [row[component['labelField']] for row in rows]
    return dict(title=title, labels=[str(row['id'] if label is None else label) for row, label in zip(rows, labels)],
                values=values, unit='GiB' if field in ('used_gib', 'total_gib', 'free_gib') else '')


def compile_surface(components, run_id, datasets):
    if not isinstance(components, list) or not 1 <= len(components) <= 12:
        raise ValueError('invalid component count')
    resolved = {}
    for item in components:
        identifier = item['id']
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,39}', identifier) or identifier in resolved:
            raise ValueError('invalid component id')
        resolved[identifier] = dict(id=identifier, component=item['component'], **component_data(item, datasets))

    visited = set()

    def visit(identifier, depth):
        if depth > 5 or identifier in visited:
            raise ValueError('invalid component tree')
        visited.add(identifier)
        for child in resolved[identifier].get('children', []):
            visit(child, depth + 1)

    visit('root', 0)
    if visited != resolved.keys():
        raise ValueError('unreachable components')
    return dict(version='1.0', createSurface=dict(surfaceId='run_'+run_id, catalogId=CATALOG_ID,
                                                 components=list(resolved.values())))


def parse_reply(raw, run_id, datasets):
    text, tag, remainder = raw.partition('<a2ui-json>')
    result = dict(content=bounded_text(text, 4000))
    if not tag:
        return result
    payload, closing, trailing = remainder.partition('</a2ui-json>')
    try:
        if not closing or trailing.strip() or len(payload) > 12000:
            raise ValueError('invalid surface envelope')
        result['a2ui'] = compile_surface(json.loads(payload), run_id, datasets)
    except (KeyError, RecursionError, TypeError, ValueError):
        result['a2ui_rejected'] = True
    return result
