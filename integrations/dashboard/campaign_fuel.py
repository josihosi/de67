"""Read-only campaign projection of retained own-response accounting.

The runner writes the existing work-context usage index. This module never ingests
rollouts, writes workspace state, or derives totals from rolling/cumulative counters.
"""
from contextlib import closing
from datetime import datetime
from pathlib import Path
import json
import sqlite3
import time


def stamp(value):
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        return parsed.timestamp() if parsed.utcoffset() is not None else None
    except (AttributeError, TypeError, ValueError, OverflowError):
        return None


def _read_campaign_fuel(workspace, sessions_root, *, now=None):
    workspace, sessions_root = Path(workspace), Path(sessions_root)
    now = time.time() if now is None else now
    config = json.loads((workspace/'.de67/state/workspace.json').read_text())['clock']
    state = Path(config['state']).expanduser()
    if not state.is_absolute(): state = workspace/state
    index = workspace/'.de67/state/work-context.sqlite3'
    roles = ('astra','coordinator','sol','terra','luna','other')
    totals = dict.fromkeys(roles, 0)
    series = {role:[0]*24 for role in roles}
    windows, gaps = {}, []
    def add(identity, start, end):
        if identity and isinstance(start,(int,float)) and (end is None or end >= start):
            windows.setdefault(identity, set()).add((start,end))
        else: gaps.append('invalid ownership window')
    with closing(sqlite3.connect(state.resolve().as_uri()+'?mode=ro',uri=True)) as d, \
         closing(sqlite3.connect(index.resolve().as_uri()+'?mode=ro',uri=True)) as u:
        u.row_factory = sqlite3.Row
        run_sessions = {row['run_id']:row['session_id'] for row in u.execute(
            'SELECT run_id,session_id FROM runs WHERE lineage=? AND session_id IS NOT NULL', (config['lineage'],))}
        for run_id,start,end in d.execute('SELECT run_id,started_at,finished_at FROM supervisor_attempts WHERE lineage_id=?',(config['lineage'],)):
            identity = run_sessions.get(run_id)
            if not identity:
                try: identity=(workspace/'.de67/state/coordinator-runs'/run_id/'session_id.txt').read_text().strip()
                except OSError: gaps.append('missing run binding');continue
            add(identity,start,end)
        for identity,start,end in d.execute('SELECT worker_id,claimed_at,released_at FROM worker_claims WHERE lineage_id=?',(config['lineage'],)):
            add(identity,start,end)
        # Native children inherit their parent's selected windows; union avoids
        # duplicate ancestry and overlapping assignments. Original roots keep theirs.
        native = sessions_root.parent/'state_5.sqlite'
        try:
            with closing(sqlite3.connect(native.resolve().as_uri()+'?mode=ro',uri=True)) as n:
                roots = list(windows.items())
                for root,spans in roots:
                    children=n.execute('WITH RECURSIVE tree(id) AS (SELECT ? UNION SELECT child_thread_id FROM thread_spawn_edges JOIN tree ON parent_thread_id=tree.id) SELECT id FROM tree',(root,))
                    for (identity,) in children:
                        if identity not in dict(roots): windows.setdefault(identity,set()).update(spans)
        except sqlite3.Error: gaps.append('descendant membership unavailable')
        known=0;first=None;last=None;responses=0
        for identity,spans in windows.items():
            source=u.execute('SELECT issues,window_start,last_event FROM usage_sources WHERE id=?',(identity,)).fetchone()
            if source is None: gaps.append('unindexed selected session');continue
            if source['issues']: gaps.append('partial source coverage')
            rows=u.execute('SELECT r.observed_at,r.usage,m.model FROM usage_responses r LEFT JOIN usage_turn_models m ON r.id=m.id AND r.turn_id=m.turn_id WHERE r.id=?',(identity,))
            selected=0
            for row in rows:
                t=stamp(row['observed_at'])
                if t is None: gaps.append('response timestamp unavailable');continue
                if not any(a <= t and (b is None or t < b) for a,b in spans):continue
                value=json.loads(row['usage'])
                delta=value['input_tokens']-value['cached_input_tokens']+value['output_tokens']
                if delta < 0: gaps.append('invalid usage');continue
                role=str(row['model']).lower().rsplit('-',1)[-1]
                if role not in roles:
                    role='other'
                    if not row['model']:gaps.append('model unavailable')
                totals[role]+=delta;selected+=1;responses+=1
                first=t if first is None else min(first,t);last=t if last is None else max(last,t)
                if now-86400 <= t <= now:
                    bucket=min(23,int((t-(now-86400))/3600))
                    series[role][bucket]+=delta
            known+=bool(selected)
        # Older traces/indexes have no seal proving all historical responses survived.
        # This is an honest observed cumulative total, never an exact all-time claim.
        return dict(available=bool(known),totals=totals,series=series,
                    bins=[sum(series[r][i] for r in roles) for i in range(24)],
                    partial=True,sessions=known,lineage=config['lineage'],
                    response_count=responses,coverage_start=first,observed_through=last,
                    gap_count=len(gaps),accounting='retained own responses; older coverage partial',
                    selected_sessions=len(windows))


_CACHE = {}

def read_campaign_fuel(workspace, sessions_root, *, now=None):
    # Ten-second in-memory display cache only; durable accounting remains in SQLite.
    # Explicit test/as-of timestamps always calculate directly.
    if now is not None:
        return _read_campaign_fuel(workspace, sessions_root, now=now)
    config = (Path(workspace)/'.de67/state/workspace.json').read_text()
    key = (str(workspace), str(sessions_root), config)
    saved = _CACHE.get(key)
    if saved and time.monotonic() - saved[0] < 10:
        return saved[1]
    value = _read_campaign_fuel(workspace, sessions_root)
    _CACHE.clear(); _CACHE[key] = (time.monotonic(), value)
    return value
