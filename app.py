"""OpenClaw Agent Dashboard backend.

This module implements a real-time observability backend for OpenClaw agents.
It combines passive core telemetry polling, event-bus tailing, session bridging,
and layered drilldown APIs (including causal graphs and node-level deep detail).

Author: Niccolò Zamborlini (encom.io)
Project: https://github.com/virgolamobile/openclaw-swarm-observatory/tree/main
"""

from flask import Flask, render_template, request, send_from_directory
from flask_socketio import SocketIO
import threading
import time
import json
import os
import shutil
import subprocess
import re
import hashlib
from datetime import datetime
from collections import deque

app = Flask(__name__)
socketio = SocketIO(app, cors_allowed_origins="*")

# Shared event bus and runtime data paths.
BUS_PATH = os.path.expanduser('~/.openclaw/shared/events/bus.jsonl')
HISTORY_DIR = os.path.expanduser('~/.openclaw/shared/events/history')
INVALID_DIR = os.path.expanduser('~/.openclaw/shared/events/invalid')
AGENTS_ROOT = os.path.expanduser('~/.openclaw/agents')
CRON_RUNS_DIR = os.path.expanduser('~/.openclaw/cron/runs')

# In-memory state cache (last known snapshot per agent).
agent_state = {}
state_lock = threading.Lock()
# Prevent starting multiple bus reader tasks
bus_reader_started = False
# Readiness flag: True when initial scan completed and agent_state populated
BUS_READY = False
bootstrap_lock = threading.Lock()
session_bridge_started = False
core_monitor_started = False
recent_user_agent = deque(maxlen=250)
recent_agent_agent = deque(maxlen=250)
interaction_seen_order = deque(maxlen=4000)
interaction_seen_set = set()
cron_details_by_agent = {}
cron_summary = {
    'active_jobs': 0,
    'next_up': [],
    'last_errors': [],
}
PRIORITY_CONTEXT_BASENAMES = ['soul.md', 'objectives.md', 'operations.md', 'agents.md', 'user.md', 'heartbeat.md']
DOCS_DIR = os.path.join(os.path.dirname(__file__), 'docs')

OPENCLAW_MODE = os.environ.get('AGENT_DASHBOARD_MODE', 'auto').strip().lower()
CORE_POLL_INTERVAL_SEC = float(os.environ.get('AGENT_DASHBOARD_CORE_POLL_SEC', '5'))
try:
    GRAPH_MAX_ACTIVATIONS = int(
        os.environ.get(
            'AGENT_DASHBOARD_GRAPH_MAX_ACTIVATIONS',
            os.environ.get('AGENT_DASHBOARD_GRAPH_MAX_OUTCOMES', '5'),
        )
    )
except Exception:
    GRAPH_MAX_ACTIVATIONS = 5
GRAPH_MAX_ACTIVATIONS = max(1, min(GRAPH_MAX_ACTIVATIONS, 24))
CORE_CAPABILITIES = {
    'provider': 'openclaw-cli',
    'openclaw_cli': False,
    'channels': {
        'agents_list': False,
        'cron_list': False,
        'status': False,
        'presence': False,
    },
    'graph': {
        'max_activations': GRAPH_MAX_ACTIVATIONS,
    },
    'mode': OPENCLAW_MODE,
}

@app.route('/')
def index():
    """Serve the main dashboard HTML page."""
    return render_template('index.html')


@app.route('/sw.js')
def service_worker():
    """Serve service worker from root to enable app-wide offline scope."""
    response = send_from_directory('static', 'sw.js')
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Content-Type'] = 'application/javascript; charset=utf-8'
    return response

@app.route('/ready')
def ready():
    """Return lightweight readiness status for frontend bootstrap retries."""
    return {'ready': bool(BUS_READY)}


@app.route('/capabilities')
def capabilities():
    """Expose runtime capabilities and currently tracked agent count."""
    with state_lock:
        tracked_agents = len(agent_state)
    return {
        'mode': OPENCLAW_MODE,
        'ready': bool(BUS_READY),
        'tracked_agents': tracked_agents,
        'capabilities': CORE_CAPABILITIES,
    }


@app.route('/insights')
def insights():
    """Return aggregated, UI-ready telemetry for the global dashboard view."""
    with state_lock:
        agents = list(agent_state.values())
        user_agent = list(recent_user_agent)
        agent_agent = list(recent_agent_agent)
        cron_by_agent = cron_details_by_agent.copy()
        cron_info = cron_summary.copy()

    def parse_mem_mb(raw_value):
        if raw_value is None:
            return None
        if isinstance(raw_value, (int, float)):
            return float(raw_value)
        text = str(raw_value).strip()
        if not text:
            return None
        match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*(kb|mb|gb|b)?', text, re.I)
        if not match:
            return None
        value = float(match.group(1))
        unit = (match.group(2) or 'mb').lower()
        if unit == 'gb':
            return value * 1024
        if unit == 'kb':
            return value / 1024
        if unit == 'b':
            return value / (1024 * 1024)
        return value

    def run_cmd(cmd):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, timeout=2)
            return (out or '').strip()
        except Exception:
            return ''

    def host_resource_probe():
        cpu_percent = None
        ram_used_mb = None
        ram_total_mb = None
        gpu_util = None
        gpu_mem_used_mb = None
        gpu_mem_total_mb = None
        gpu_source = 'none'

        cpu_raw = run_cmd(['sh', '-lc', "ps -A -o %cpu= | awk '{s+=$1} END {printf \"%.1f\", s}'"])
        try:
            if cpu_raw:
                cpu_percent = float(cpu_raw)
        except Exception:
            cpu_percent = None

        rss_raw = run_cmd(['sh', '-lc', "ps -A -o rss= | awk '{s+=$1} END {printf \"%.0f\", s}'"])
        memsize_raw = run_cmd(['sysctl', '-n', 'hw.memsize'])
        try:
            if rss_raw:
                ram_used_mb = float(rss_raw) / 1024.0
        except Exception:
            ram_used_mb = None
        try:
            if memsize_raw:
                ram_total_mb = float(memsize_raw) / (1024.0 * 1024.0)
        except Exception:
            ram_total_mb = None

        nvidia_smi = shutil.which('nvidia-smi')
        if nvidia_smi:
            gpu_raw = run_cmd([
                nvidia_smi,
                '--query-gpu=utilization.gpu,memory.used,memory.total',
                '--format=csv,noheader,nounits',
            ])
            if gpu_raw:
                first_line = gpu_raw.splitlines()[0]
                parts = [p.strip() for p in first_line.split(',')]
                try:
                    if len(parts) >= 1 and parts[0]:
                        gpu_util = float(parts[0])
                    if len(parts) >= 2 and parts[1]:
                        gpu_mem_used_mb = float(parts[1])
                    if len(parts) >= 3 and parts[2]:
                        gpu_mem_total_mb = float(parts[2])
                    gpu_source = 'nvidia-smi'
                except Exception:
                    gpu_source = 'nvidia-smi-unparsed'

        return {
            'cpu_percent': cpu_percent,
            'ram_used_mb': ram_used_mb,
            'ram_total_mb': ram_total_mb,
            'gpu_util_percent': gpu_util,
            'gpu_mem_used_mb': gpu_mem_used_mb,
            'gpu_mem_total_mb': gpu_mem_total_mb,
            'gpu_source': gpu_source,
        }

    def parse_tokens(agent_row):
        raw = agent_row.get('raw') if isinstance(agent_row.get('raw'), dict) else {}
        raw_core = agent_row.get('raw_core') if isinstance(agent_row.get('raw_core'), dict) else {}
        candidates = [
            raw_core.get('totalTokens'),
            raw_core.get('total_tokens'),
            (raw_core.get('usage') or {}).get('totalTokens') if isinstance(raw_core.get('usage'), dict) else None,
            (raw_core.get('usage') or {}).get('total_tokens') if isinstance(raw_core.get('usage'), dict) else None,
            raw.get('totalTokens'),
            raw.get('total_tokens'),
            (raw.get('usage') or {}).get('totalTokens') if isinstance(raw.get('usage'), dict) else None,
            (raw.get('usage') or {}).get('total_tokens') if isinstance(raw.get('usage'), dict) else None,
        ]
        for candidate in candidates:
            try:
                if candidate is not None:
                    return float(candidate)
            except Exception:
                continue

        for message in agent_row.get('recent_messages') or []:
            m = re.search(r'tokens\s*[=:]\s*([0-9]+)', str(message), re.I)
            if m:
                try:
                    return float(m.group(1))
                except Exception:
                    continue
        return None

    mem_numeric = 0
    tokens_numeric = 0
    both_numeric = 0
    telemetry_missing = []
    for row in agents:
        mem_mb = parse_mem_mb(
            row.get('mem')
            if row.get('mem') not in ('', None)
            else (row.get('memory') or row.get('rss') or ((row.get('raw') or {}).get('memory') if isinstance(row.get('raw'), dict) else None))
        )
        if mem_mb is None and isinstance(row.get('raw_core'), dict):
            mem_mb = parse_mem_mb(row.get('raw_core', {}).get('memory') or row.get('raw_core', {}).get('rss'))

        tokens = parse_tokens(row)

        has_mem = mem_mb is not None
        has_tokens = tokens is not None
        if has_mem:
            mem_numeric += 1
        if has_tokens:
            tokens_numeric += 1
        if has_mem and has_tokens:
            both_numeric += 1

        missing = []
        if not has_mem:
            missing.append('ram')
        if not has_tokens:
            missing.append('tokens')
        if missing:
            telemetry_missing.append({
                'agent': row.get('agent') or 'unknown',
                'missing': missing,
                'status': row.get('status') or 'unknown',
                'last_seen': row.get('last_seen') or '',
            })

    resources = host_resource_probe()

    return {
        'generated_at': utc_now_iso(),
        'agents': agents,
        'resource_probe': resources,
        'telemetry_gaps': {
            'summary': {
                'agents': len(agents),
                'ram_numeric': mem_numeric,
                'tokens_numeric': tokens_numeric,
                'both_numeric': both_numeric,
            },
            'agents': telemetry_missing,
        },
        'interactions': {
            'user_agent': user_agent,
            'agent_agent': agent_agent,
        },
        'cron': {
            'summary': cron_info,
            'by_agent': cron_by_agent,
        },
    }


def get_docs_manifest():
    """Return a deterministic list of available markdown docs for in-app help."""
    if not os.path.isdir(DOCS_DIR):
        return []

    docs = []
    try:
        names = sorted(os.listdir(DOCS_DIR))
    except Exception:
        return []

    for name in names:
        if not name.lower().endswith('.md'):
            continue
        file_path = os.path.join(DOCS_DIR, name)
        if not os.path.isfile(file_path):
            continue
        docs.append({
            'name': name,
            'path': file_path,
            'is_index': name.lower() == 'index.md',
        })

    docs.sort(key=lambda item: (0 if item.get('is_index') else 1, item.get('name', '').lower()))
    return docs


@app.route('/docs/index')
def docs_index():
    """Expose documentation index metadata for in-app documentation modal."""
    docs = get_docs_manifest()
    return {
        'count': len(docs),
        'docs': [
            {
                'name': item.get('name', ''),
                'is_index': bool(item.get('is_index')),
            }
            for item in docs
        ],
    }


@app.route('/docs/content/<path:doc_name>')
def docs_content(doc_name):
    """Return markdown content for one known docs file (safe, whitelisted)."""
    docs = get_docs_manifest()
    normalized = str(doc_name or '').strip()
    if not normalized:
        return {'found': False, 'error': 'doc_not_found'}, 404

    row = next((item for item in docs if item.get('name') == normalized), None)
    if row is None:
        return {'found': False, 'error': 'doc_not_found', 'doc': normalized}, 404

    try:
        with open(row['path'], 'r', encoding='utf-8') as handle:
            content = handle.read()
    except Exception:
        return {'found': False, 'error': 'doc_read_failed', 'doc': normalized}, 500

    return {
        'found': True,
        'doc': row.get('name', ''),
        'is_index': bool(row.get('is_index')),
        'content': content,
    }


@app.route('/drilldown/<agent_name>')
def drilldown(agent_name):
    """Return full drilldown payload for a specific agent."""
    target = normalize_agent_name(agent_name)
    max_activations = request.args.get('max_activations', type=int)
    if max_activations is None:
        max_activations = request.args.get('max_outcomes', type=int)
    with state_lock:
        snapshot = find_agent_snapshot(target)
        if snapshot is None:
            return {
                'agent': agent_name,
                'found': False,
                'error': 'agent_not_found',
            }, 404
        depth = compute_drilldown_depth(snapshot, target, max_activations=max_activations)

    return {
        'agent': snapshot.get('agent', target),
        'found': True,
        'generated_at': utc_now_iso(),
        'depth': depth,
    }


@app.route('/drilldown/<agent_name>/node/<path:node_id>')
def drilldown_node(agent_name, node_id):
    """Return node-level deep details for a selected causal graph node."""
    target = normalize_agent_name(agent_name)
    max_activations = request.args.get('max_activations', type=int)
    if max_activations is None:
        max_activations = request.args.get('max_outcomes', type=int)
    with state_lock:
        snapshot = find_agent_snapshot(target)
        if snapshot is None:
            return {
                'agent': agent_name,
                'found': False,
                'error': 'agent_not_found',
            }, 404
        depth = compute_drilldown_depth(snapshot, target, max_activations=max_activations)
        graph = depth.get('causal_graph', {}) if isinstance(depth, dict) else {}
        nodes = graph.get('nodes', []) if isinstance(graph, dict) else []
        edges = graph.get('edges', []) if isinstance(graph, dict) else []

        node = next((n for n in nodes if str(n.get('id', '')) == str(node_id)), None)
        if node is None:
            return {
                'agent': snapshot.get('agent', target),
                'found': False,
                'error': 'node_not_found',
                'node_id': node_id,
            }, 404

        inbound = [e for e in edges if str(e.get('target', '')) == str(node_id)][:30]
        outbound = [e for e in edges if str(e.get('source', '')) == str(node_id)][:30]
        related_ids = set()
        for edge in inbound + outbound:
            related_ids.add(str(edge.get('source', '')))
            related_ids.add(str(edge.get('target', '')))
        related = [n for n in nodes if str(n.get('id', '')) in related_ids and str(n.get('id', '')) != str(node_id)][:30]

        context_roots = depth.get('context_roots', []) if isinstance(depth, dict) else []
        file_detail = None
        meta = node.get('meta', {}) if isinstance(node.get('meta', {}), dict) else {}
        file_path = meta.get('file')
        if isinstance(file_path, str) and file_path:
            file_entry = next((r for r in context_roots if r.get('file') == file_path), None)
            if file_entry:
                file_detail = {
                    'file': file_entry.get('file', ''),
                    'matched_anchors': file_entry.get('matched_anchors', []),
                    'sample': file_entry.get('sample', ''),
                }

    return {
        'agent': snapshot.get('agent', target),
        'found': True,
        'node': node,
        'related_nodes': related,
        'inbound_edges': inbound,
        'outbound_edges': outbound,
        'file_detail': file_detail,
    }


def compute_drilldown_depth(snapshot, target, max_activations=None):
    """Build all layered drilldown sections for one agent snapshot."""
    timeline = build_agent_timeline(snapshot)
    agent_cron = cron_details_by_agent.get(snapshot.get('agent', ''), [])
    cron_timeline = build_cron_timeline(agent_cron)
    context_roots = load_agent_context_roots(snapshot)
    decisions = infer_decision_trace(target, timeline, context_roots)
    causal_graph = build_causal_graph(
        snapshot,
        decisions,
        cron_timeline,
        context_roots,
        timeline=timeline,
        max_activations=max_activations,
    )
    return {
        'overview': {
            'status': snapshot.get('status', 'unknown'),
            'task': snapshot.get('task', ''),
            'last_seen': snapshot.get('last_seen', ''),
            'cron_jobs': snapshot.get('cron_jobs', 0),
            'interrupted_tasks': snapshot.get('interrupted_tasks', []),
        },
        'timeline': timeline[:180],
        'decision_trace': decisions,
        'cron': agent_cron,
        'cron_timeline': cron_timeline,
        'context_roots': context_roots,
        'causal_graph': causal_graph,
    }


def should_skip_event(event):
    """Filter out invalid/system events that should not update agent state."""
    if not isinstance(event, dict):
        return True
    if event.get('from') == 'system' or event.get('type') == 'announcement':
        return True
    if 'agent' not in event and 'source' not in event:
        return True
    return False


def normalize_event(event):
    """Normalize incoming events into a stable dashboard schema."""
    agent = event.get('agent') or event.get('source') or 'unknown'
    return {
        'agent': agent,
        'status': event.get('status', 'unknown'),
        'task': event.get('task', ''),
        'last_seen': event.get('ts') or event.get('time') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'cron_jobs': event.get('cron_jobs') if 'cron_jobs' in event else None,
        'active_missions': event.get('active_missions') if 'active_missions' in event else None,
        'cpu': event.get('cpu') if 'cpu' in event else None,
        'mem': event.get('mem') if 'mem' in event else None,
        'recent_messages': event.get('recent_messages') if 'recent_messages' in event else None,
        'recent_thoughts': event.get('recent_thoughts') if 'recent_thoughts' in event else None,
        'current_thought': event.get('current_thought') if 'current_thought' in event else None,
        'real_time': event.get('real_time', True),
        'raw': event,
    }


def utc_now_iso():
    """Return current UTC time as ISO-8601 string."""
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def normalize_agent_name(name):
    """Normalize an agent identifier for reliable lookups."""
    return str(name or '').strip().lower()


def find_agent_snapshot(target_name):
    """Retrieve a cached agent snapshot by normalized agent name."""
    for item in agent_state.values():
        current = normalize_agent_name(item.get('agent', ''))
        if current == target_name:
            return item
    return None


def get_agent_registry():
    """Read core agent registry from OpenClaw CLI."""
    payload = run_openclaw_json(['agents', 'list'])
    if not isinstance(payload, list):
        return []
    return payload


def read_text_file_head(path, max_bytes=32000):
    """Read a bounded text prefix from file for safe context analysis."""
    try:
        with open(path, 'r', encoding='utf-8') as fp:
            return fp.read(max_bytes)
    except Exception:
        return ''


def tokenize_text(text):
    """Extract normalized word tokens used by heuristic matching."""
    if not isinstance(text, str):
        return set()
    return set(re.findall(r'[a-zA-Z0-9àèéìòù_-]{4,}', text.lower()))


def extract_document_anchors(text, max_items=32):
    """Extract potentially meaningful anchors from markdown-like text."""
    anchors = []
    if not isinstance(text, str):
        return anchors
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in lines:
        if line.startswith('#'):
            anchors.append(line.lstrip('#').strip())
        elif line.startswith('- ') or line.startswith('* '):
            anchors.append(line[2:].strip())
        elif re.match(r'^\d+[\.)]\s+', line):
            anchors.append(re.sub(r'^\d+[\.)]\s+', '', line).strip())
        elif any(keyword in line.lower() for keyword in ['must', 'always', 'never', 'objective', 'mission', 'priority']):
            anchors.append(line)
        if len(anchors) >= max_items:
            break
    return anchors


def best_anchor_matches(anchors, reference_text, max_items=5):
    """Score and return anchors with strongest lexical overlap."""
    ref_tokens = tokenize_text(reference_text)
    scored = []
    for anchor in anchors:
        tokens = tokenize_text(anchor)
        if not tokens:
            continue
        overlap = len(tokens.intersection(ref_tokens))
        if overlap > 0:
            scored.append((overlap, anchor))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [item[1] for item in scored[:max_items]]


def resolve_agent_workspace(snapshot):
    """Resolve workspace path for an agent snapshot via core metadata/fallbacks."""
    raw_core = snapshot.get('raw_core') if isinstance(snapshot.get('raw_core'), dict) else {}
    workspace = raw_core.get('workspace')
    if isinstance(workspace, str) and workspace:
        return workspace

    agent_name = normalize_agent_name(snapshot.get('agent', ''))
    for entry in get_agent_registry():
        if not isinstance(entry, dict):
            continue
        candidate_id = normalize_agent_name(entry.get('id', ''))
        candidate_name = normalize_agent_name(entry.get('name', ''))
        if agent_name in {candidate_id, candidate_name}:
            ws = entry.get('workspace')
            if isinstance(ws, str) and ws:
                return ws

    fallback_paths = [
        os.path.expanduser(f'~/.openclaw/workspace-{snapshot.get("agent", "")}'),
        os.path.expanduser(f'~/.openclaw/workspace-{snapshot.get("agent", "").lower()}'),
    ]
    for path in fallback_paths:
        if os.path.isdir(path):
            return path
    return ''


def discover_workspace_markdown_files(workspace, max_files=80):
    """Discover markdown context files dynamically (no fixed filename assumption)."""
    if not workspace or not os.path.isdir(workspace):
        return []

    ignored_dirs = {'.git', '.venv', 'venv', 'node_modules', '__pycache__', '.idea', '.vscode'}
    candidates = []
    for root, dirs, files in os.walk(workspace):
        rel = os.path.relpath(root, workspace)
        depth = 0 if rel == '.' else rel.count(os.sep) + 1
        dirs[:] = [d for d in dirs if d not in ignored_dirs and not d.startswith('.')]
        if depth > 4:
            dirs[:] = []
            continue
        for name in files:
            if not name.lower().endswith('.md'):
                continue
            path = os.path.join(root, name)
            try:
                size = os.path.getsize(path)
            except Exception:
                size = 0
            if size <= 0 or size > 512000:
                continue
            basename = name.lower()
            priority = 0
            if basename in PRIORITY_CONTEXT_BASENAMES:
                priority += 100
            if 'soul' in basename:
                priority += 60
            if 'operation' in basename or 'objective' in basename or 'agent' in basename:
                priority += 30
            if rel == '.':
                priority += 15
            priority -= depth * 3
            candidates.append((priority, path))

    candidates.sort(key=lambda item: (-item[0], item[1]))
    return [item[1] for item in candidates[:max_files]]


def load_agent_context_roots(snapshot):
    """Load context-root documents and compute best anchor matches for one agent."""
    workspace = resolve_agent_workspace(snapshot)
    if not workspace:
        return []

    reference = ' '.join([
        str(snapshot.get('task', '')),
        ' '.join([str(x) for x in (snapshot.get('recent_messages') or [])[-5:]]),
        ' '.join([str(x) for x in (snapshot.get('recent_thoughts') or [])[-5:]]),
    ])

    roots = []
    markdown_files = discover_workspace_markdown_files(workspace, max_files=70)
    for path in markdown_files:
        content = read_text_file_head(path)
        if not content:
            continue
        anchors = extract_document_anchors(content, max_items=36)
        matched = best_anchor_matches(anchors, reference, max_items=6)
        roots.append({
            'file': path,
            'anchors': anchors[:16],
            'matched_anchors': matched,
            'sample': '\n'.join(content.splitlines()[:24]),
        })
    return roots


def parse_any_ts(value):
    """Parse timestamp-like values into comparable epoch seconds."""
    def normalize_epoch(raw):
        try:
            num = float(raw)
        except Exception:
            return 0.0
        if num <= 0:
            return 0.0
        if num > 1e18:
            num = num / 1e9
        elif num > 1e15:
            num = num / 1e6
        elif num > 1e12:
            num = num / 1e3
        return float(num)

    if isinstance(value, (int, float)):
        return normalize_epoch(value)
    if not isinstance(value, str):
        return 0.0
    text = value.strip()
    if not text:
        return 0.0
    if re.fullmatch(r'[-+]?\d+(?:\.\d+)?', text):
        return normalize_epoch(text)
    try:
        if text.endswith('Z'):
            text = text[:-1] + '+00:00'
        return datetime.fromisoformat(text).timestamp()
    except Exception:
        return 0.0


def build_agent_timeline(snapshot):
    """Build a unified timeline combining session, interaction, and cron evidence."""
    timeline = []
    agent = snapshot.get('agent', 'unknown')
    message_history = snapshot.get('message_history') or []
    thought_history = snapshot.get('thought_history') or []
    recent_messages = snapshot.get('recent_messages') or []
    recent_thoughts = snapshot.get('recent_thoughts') or []
    cron_jobs = snapshot.get('cron_details') or []

    for row in message_history[-120:]:
        if not isinstance(row, dict):
            continue
        timeline.append({
            'ts': row.get('ts') or '',
            'source': 'session',
            'type': 'message',
            'text': str(row.get('text') or '')[:500],
        })

    for row in thought_history[-120:]:
        if not isinstance(row, dict):
            continue
        timeline.append({
            'ts': row.get('ts') or '',
            'source': 'session',
            'type': 'thought',
            'text': str(row.get('text') or '')[:500],
        })

    for text in recent_messages[-8:]:
        actor, content = parse_message_actor(str(text))
        timeline.append({
            'ts': snapshot.get('last_seen', ''),
            'source': 'realtime',
            'type': f'recent_{actor}',
            'text': content[:500],
        })

    for text in recent_thoughts[-8:]:
        timeline.append({
            'ts': snapshot.get('last_seen', ''),
            'source': 'realtime',
            'type': 'recent_thought',
            'text': str(text)[:500],
        })

    for job in cron_jobs:
        if not isinstance(job, dict):
            continue
        name = job.get('name', 'cron')
        summary = job.get('summary') or ''
        timeline.append({
            'ts': job.get('last_run_at') or '',
            'source': 'cron',
            'type': 'cron_last_run',
            'text': f"{name}: {summary}"[:500],
        })
        for run in (job.get('recent_runs') or [])[-6:]:
            if not isinstance(run, dict):
                continue
            action = run.get('action', 'run')
            status = run.get('status', 'unknown')
            text = run.get('summary') or ''
            run_ts_ms = run.get('ts')
            run_ts = fmt_ts_ms(run_ts_ms) if isinstance(run_ts_ms, (int, float)) else ''
            timeline.append({
                'ts': run_ts,
                'source': 'cron-run',
                'type': f'cron_{action}_{status}',
                'text': text[:500],
            })

    for row in list(recent_user_agent):
        if not isinstance(row, dict):
            continue
        if normalize_agent_name(row.get('agent')) != normalize_agent_name(agent):
            continue
        timeline.append({
            'ts': row.get('ts', ''),
            'source': 'interaction',
            'type': f"{row.get('actor', 'unknown')}_interaction",
            'text': str(row.get('text', ''))[:500],
        })

    deduped = []
    seen = set()
    for item in timeline:
        key = (
            str(item.get('source', '')).strip().lower(),
            str(item.get('type', '')).strip().lower(),
            str(item.get('text', '')).strip().lower(),
        )
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    timeline = deduped

    timeline.sort(key=lambda item: parse_any_ts(item.get('ts')), reverse=True)
    return timeline


def build_cron_timeline(agent_cron):
    """Build chronological cron timeline events for a single agent."""
    items = []
    now_ms = int(time.time() * 1000)
    for job in agent_cron:
        if not isinstance(job, dict):
            continue
        name = job.get('name', 'cron')
        next_ms = job.get('next_run_ms')
        if isinstance(next_ms, (int, float)):
            items.append({
                'ts_ms': next_ms,
                'ts': fmt_ts_ms(next_ms),
                'kind': 'next_run',
                'job': name,
                'status': 'scheduled',
                'summary': job.get('next_action', ''),
                'in_seconds': max(0, int((next_ms - now_ms) / 1000)),
            })
        for run in (job.get('recent_runs') or [])[-8:]:
            if not isinstance(run, dict):
                continue
            ts_ms = run.get('ts')
            if not isinstance(ts_ms, (int, float)):
                continue
            items.append({
                'ts_ms': ts_ms,
                'ts': fmt_ts_ms(ts_ms),
                'kind': run.get('action', 'run'),
                'job': name,
                'status': run.get('status', 'unknown'),
                'summary': run.get('summary', ''),
                'duration_ms': run.get('durationMs'),
                'next_run_ms': run.get('nextRunAtMs'),
            })
    items.sort(key=lambda x: x.get('ts_ms', 0), reverse=False)
    return items[-180:]


def infer_decision_trace(agent_name, timeline, context_roots=None):
    """Infer decision records with runtime evidence and root-cause document links."""
    decisions = []
    working = timeline[:220]
    context_roots = context_roots or []

    for idx, row in enumerate(working):
        if not isinstance(row, dict):
            continue
        entry_type = str(row.get('type', '')).lower()
        text = str(row.get('text', '')).strip()
        if not text:
            continue

        decision_candidate = (
            entry_type.startswith('recent_assistant')
            or entry_type == 'message'
            or entry_type in {'user_interaction', 'assistant_interaction'}
            or 'cron_finished_ok' in entry_type
            or 'cron_last_run' in entry_type
        )
        if not decision_candidate:
            continue

        reasons = []
        evidence = []
        for prev in working[idx + 1: idx + 10]:
            prev_type = str(prev.get('type', '')).lower()
            prev_text = str(prev.get('text', '')).strip()
            if not prev_text:
                continue
            if 'recent_user' in prev_type or 'user_interaction' in prev_type:
                reasons.append('Recent user request')
                evidence.append(prev_text[:260])
                break
            if 'cron_' in prev_type:
                reasons.append('Triggered by cron execution')
                evidence.append(prev_text[:260])
                break
            if 'thought' in prev_type:
                reasons.append('Recent reasoning chain')
                evidence.append(prev_text[:260])
                break

        if not reasons:
            reasons.append('Continuous operational context')

        root_causes = []
        for root in context_roots:
            if not isinstance(root, dict):
                continue
            matches = best_anchor_matches(root.get('anchors', []), text, max_items=3)
            if matches:
                root_causes.append({
                    'file': root.get('file', ''),
                    'anchors': matches,
                })

        if root_causes:
            reasons.append('Constraints/goals derived from workspace documents (SOUL/OPERATIONS/...)')

        confidence = 'high' if evidence else 'medium'
        decisions.append({
            'ts': row.get('ts', ''),
            'agent': agent_name.capitalize(),
            'decision': text[:320],
            'why': reasons,
            'evidence': evidence,
            'confidence': confidence,
            'source': row.get('source', ''),
            'type': row.get('type', ''),
            'root_causes': root_causes,
        })

        if len(decisions) >= 25:
            break

    return decisions


def clip_text(value, max_len=140):
    """Clamp text length to keep graph nodes and labels readable."""
    text = str(value or '').strip().replace('\n', ' ')
    if len(text) <= max_len:
        return text
    return text[:max_len - 1] + '…'


def build_causal_graph(snapshot, decisions, cron_timeline, context_roots, timeline=None, max_activations=None):
    """Build causal graph nodes/edges with explicit cause→effect reasoning paths."""
    nodes = []
    edges = []
    node_ids = set()
    node_by_id = {}

    confidence_weight = {
        'high': 0.68,
        'medium': 0.48,
        'low': 0.34,
    }

    def clamp_weight(value):
        try:
            num = float(value)
        except Exception:
            return 0.1
        if num < 0.1:
            return 0.1
        if num > 1.9:
            return 1.9
        return num

    def add_node(node_id, label, group, meta=None):
        if node_id in node_ids:  # pragma: no cover
            return
        node_ids.add(node_id)
        payload = {
            'id': node_id,
            'label': clip_text(label, 120),
            'group': group,
            'meta': meta or {},
        }
        payload['meta']['weight'] = clamp_weight(payload['meta'].get('weight', 0.45))
        nodes.append(payload)
        node_by_id[node_id] = payload

    def add_edge(source, target, label, meta=None):
        edge_meta = meta or {}
        edge_meta['weight'] = clamp_weight(edge_meta.get('weight', 0.45))
        edges.append({
            'source': source,
            'target': target,
            'label': clip_text(label, 72),
            'meta': edge_meta,
        })

    agent = snapshot.get('agent', 'Agent')
    agent_node = f'agent:{normalize_agent_name(agent)}'
    add_node(agent_node, agent, 'agent', {
        'status': snapshot.get('status', 'unknown'),
        'task': snapshot.get('task', ''),
        'weight': 0.8,
    })

    root_nodes = {}
    for idx, root in enumerate((context_roots or [])[:6]):
        file_path = str(root.get('file', ''))
        label = os.path.basename(file_path) if file_path else f'root-{idx + 1}'
        matches = root.get('matched_anchors') or []
        node_id = f'root:{idx}'
        add_node(node_id, label, 'root', {
            'file': file_path,
            'anchors': matches,
            'root_index': idx,
            'jump_tab': 'soul',
            'weight': clamp_weight(0.56 + min(len(matches), 4) * 0.1),
        })
        add_edge(node_id, agent_node, 'context', {
            'weight': 0.62,
        })
        root_nodes[file_path] = node_id

    if isinstance(max_activations, int):
        effective_max_activations = max(1, min(max_activations, 24))
    else:
        effective_max_activations = GRAPH_MAX_ACTIVATIONS

    activation_candidates = []
    for idx, row in enumerate(timeline or []):
        if not isinstance(row, dict):
            continue
        entry_type = str(row.get('type', '')).lower()
        source = str(row.get('source', '')).lower()
        text = str(row.get('text', '')).strip()
        ts_value = parse_any_ts(row.get('ts'))
        if ts_value <= 0 or not text:
            continue

        kind = None
        if 'user_interaction' in entry_type or entry_type.startswith('recent_user'):
            kind = 'user_request'
        elif 'assistant_interaction' in entry_type:
            kind = 'agent_request'
        elif entry_type.startswith('cron_') or source in {'cron-run', 'cron'}:
            kind = 'cron_trigger'
        elif entry_type == 'message' and source in {'session', 'interaction'}:
            kind = 'conversation'

        if not kind:
            continue

        activation_candidates.append({
            'ts': ts_value,
            'text': text,
            'kind': kind,
            'index': idx,
        })

    activation_candidates.sort(key=lambda item: (-item['ts'], item['index']))
    dedup = set()
    activation_nodes = []
    for item in activation_candidates:
        key = (item['kind'], item['text'].lower())
        if key in dedup:
            continue
        dedup.add(key)
        activation_nodes.append(item)
        if len(activation_nodes) >= effective_max_activations:
            break

    activation_nodes_by_id = []
    for idx, item in enumerate(activation_nodes):
        node_id = f'activation:{idx}'
        kind = item['kind']
        if kind == 'user_request':
            label = f"User asks: {item['text']}"
        elif kind == 'agent_request':
            label = f"Agent request: {item['text']}"
        elif kind == 'cron_trigger':
            label = f"Cron trigger: {item['text']}"
        else:
            label = f"Activation: {item['text']}"

        activation_weight = clamp_weight(0.54 + max(0.0, 0.18 - idx * 0.02))
        add_node(node_id, label, 'activation', {
            'ts': item['ts'],
            'activation_kind': kind,
            'jump_tab': 'timeline',
            'weight': activation_weight,
        })
        add_edge(node_id, agent_node, 'activates', {
            'weight': activation_weight,
        })
        activation_nodes_by_id.append((node_id, item['ts'], kind))

    decision_nodes = []
    for idx, decision in enumerate((decisions or [])[:12]):
        confidence = str(decision.get('confidence', 'medium')).strip().lower()
        evidence_count = len([x for x in (decision.get('evidence') or []) if str(x).strip()])
        root_count = len([x for x in (decision.get('root_causes') or []) if isinstance(x, dict)])
        recency_boost = max(0.0, 0.2 - (idx * 0.016))
        decision_weight = clamp_weight(
            confidence_weight.get(confidence, 0.44)
            + min(evidence_count, 4) * 0.07
            + min(root_count, 4) * 0.05
            + recency_boost
        )
        node_id = f'decision:{idx}'
        add_node(node_id, decision.get('decision', 'decision'), 'decision', {
            'ts': decision.get('ts', ''),
            'confidence': decision.get('confidence', 'n/a'),
            'why': decision.get('why', []),
            'decision_index': idx,
            'jump_tab': 'decisions',
            'weight': decision_weight,
        })
        add_edge(agent_node, node_id, 'decides', {
            'weight': max(0.52, decision_weight - 0.15),
        })

        decision_ts = parse_any_ts(decision.get('ts'))
        if activation_nodes_by_id:
            if decision_ts > 0:
                linked_activations = [entry for entry in activation_nodes_by_id if entry[1] <= decision_ts]
            else:
                linked_activations = activation_nodes_by_id
            for activation_id, _activation_ts, _kind in linked_activations[:2]:
                activation_weight = clamp_weight((node_by_id.get(activation_id) or {}).get('meta', {}).get('weight', 0.45))
                add_edge(activation_id, node_id, 'initiates', {
                    'weight': clamp_weight((activation_weight + decision_weight) / 2),
                })

        if decision_nodes:
            previous_node = node_by_id.get(decision_nodes[-1])
            previous_weight = clamp_weight((previous_node or {}).get('meta', {}).get('weight', 0.45))
            add_edge(decision_nodes[-1], node_id, 'evolves', {
                'weight': clamp_weight((previous_weight + decision_weight) / 2),
            })

        why_items = [str(x).strip() for x in (decision.get('why') or []) if str(x).strip()]
        for why_idx, reason_text in enumerate(why_items[:2]):
            reason_id = f'reason:{idx}:{why_idx}'
            reason_weight = clamp_weight(decision_weight * (0.84 - why_idx * 0.08))
            add_node(reason_id, reason_text, 'reason', {
                'decision_index': idx,
                'jump_tab': 'decisions',
                'weight': reason_weight,
            })
            add_edge(reason_id, node_id, 'motivates', {
                'weight': reason_weight,
            })

        evidence_items = [str(x).strip() for x in (decision.get('evidence') or []) if str(x).strip()]
        if evidence_items:
            evidence_id = f'signal:{idx}'
            signal_weight = clamp_weight(decision_weight * 0.78)
            add_node(evidence_id, evidence_items[0], 'signal', {
                'decision_index': idx,
                'jump_tab': 'decisions',
                'weight': signal_weight,
            })
            add_edge(evidence_id, node_id, 'supports', {
                'weight': signal_weight,
            })

        for root_ref in decision.get('root_causes', [])[:3]:
            ref_file = root_ref.get('file', '')
            root_id = root_nodes.get(ref_file)
            if root_id:
                root_weight = clamp_weight((node_by_id.get(root_id) or {}).get('meta', {}).get('weight', 0.4))
                add_edge(root_id, node_id, 'constrains', {
                    'weight': clamp_weight((root_weight + decision_weight) / 2),
                })
        decision_nodes.append(node_id)

    decision_times = []
    for idx, decision in enumerate((decisions or [])[:12]):
        decision_times.append((idx, parse_any_ts(decision.get('ts'))))

    action_nodes = []
    eligible_actions = []
    for abs_idx, row in enumerate(cron_timeline or []):
        kind = str(row.get('kind', 'event'))
        if kind not in {'finished', 'next_run', 'started', 'run'}:
            continue
        eligible_actions.append((abs_idx, row))

    for abs_idx, row in eligible_actions[-14:]:
        node_id = f'action:{abs_idx}'
        action_kind = str(row.get('kind', 'event'))
        summary = row.get('summary') or row.get('job') or action_kind
        status = str(row.get('status', 'unknown')).strip().lower()
        action_recency = max(0.0, 0.24 - ((len(eligible_actions) - abs_idx - 1) * 0.012))
        action_weight = clamp_weight(
            0.52
            + (0.18 if status in {'ok', 'success', 'scheduled'} else 0.32)
            + action_recency
        )
        add_node(node_id, summary, 'action', {
            'ts': row.get('ts', ''),
            'job': row.get('job', ''),
            'kind': action_kind,
            'status': row.get('status', ''),
            'action_index': abs_idx,
            'jump_tab': 'cron_timeline',
            'weight': action_weight,
        })

        linked_decision = None
        action_ts = parse_any_ts(row.get('ts'))
        if decision_times:
            prior = [item for item in decision_times if item[1] <= action_ts and item[1] > 0]
            if prior:
                linked_decision = prior[-1][0]
            else:
                linked_decision = min(len(decision_times) - 1, abs_idx)

        if decision_nodes:
            decision_index = linked_decision if linked_decision is not None else min(abs_idx, len(decision_nodes) - 1)
            decision_id = decision_nodes[decision_index]
            decision_weight = clamp_weight((node_by_id.get(decision_id) or {}).get('meta', {}).get('weight', 0.45))
            add_edge(decision_id, node_id, 'executes', {
                'weight': clamp_weight((decision_weight + action_weight) / 2),
            })
        else:
            add_edge(agent_node, node_id, 'acts', {
                'weight': action_weight,
            })
            decision_id = None
        action_nodes.append((node_id, row, abs_idx, decision_id))

    outcome_source_nodes = action_nodes
    for action_id, row, abs_idx, decision_id in outcome_source_nodes:
        status = str(row.get('status', 'unknown')).lower()
        outcome_id = f'outcome:{abs_idx}'
        action_weight = clamp_weight((node_by_id.get(action_id) or {}).get('meta', {}).get('weight', 0.45))
        if status in {'ok', 'success', 'scheduled'}:
            outcome_label = f"Outcome {status}: {row.get('job', '')}"
            group = 'outcome_ok'
            outcome_weight = clamp_weight(action_weight * 0.92)
        else:
            outcome_label = f"Outcome {status}: {row.get('job', '')}"
            group = 'outcome_bad'
            outcome_weight = clamp_weight(action_weight * 1.06)
        add_node(outcome_id, outcome_label, group, {
            'status': row.get('status', ''),
            'ts': row.get('ts', ''),
            'action_index': abs_idx,
            'jump_tab': 'cron_timeline',
            'weight': outcome_weight,
        })
        add_edge(action_id, outcome_id, 'produces', {
            'weight': clamp_weight((action_weight + outcome_weight) / 2),
        })

    now_ts = time.time()
    live_tail_sec = 5.0
    max_live_from_start_sec = 5.0
    snapshot_last_seen_ts = parse_any_ts(snapshot.get('last_seen'))

    def set_node_live(node_id, start_ts, activity_duration_sec):
        if not node_id:
            return False
        if not isinstance(start_ts, (int, float)) or start_ts <= 0:
            return False
        duration = max(0.0, float(activity_duration_sec or 0.0))
        expires_at = min(start_ts + max_live_from_start_sec, start_ts + duration + live_tail_sec)
        if expires_at <= start_ts:
            expires_at = start_ts + 0.25
        if now_ts < start_ts or now_ts > expires_at:
            return False
        node = node_by_id.get(node_id)
        if not node:
            return False
        meta = node.setdefault('meta', {})
        meta['live'] = True
        meta['live_started_at'] = start_ts
        meta['live_expires_at'] = expires_at
        meta['activity_duration_sec'] = duration
        return True

    def set_node_live_window(node_id, start_ts, end_ts, min_duration_sec=0.6):
        if not node_id:
            return False
        if not isinstance(start_ts, (int, float)) or start_ts <= 0:
            return False
        if not isinstance(end_ts, (int, float)) or end_ts <= 0:
            return False
        effective_end = max(end_ts, start_ts + float(min_duration_sec))
        return set_node_live(node_id, start_ts, max(0.0, effective_end - start_ts))

    live_activation_nodes = []
    for activation_id, activation_ts, _kind in activation_nodes_by_id:
        if activation_ts <= 0:
            continue
        if set_node_live_window(activation_id, activation_ts, activation_ts + 0.8, min_duration_sec=0.6):
            live_activation_nodes.append((activation_id, activation_ts))

    decision_ts_by_idx = {}
    for idx, ts in decision_times:
        decision_ts_by_idx[idx] = ts

    live_decision_nodes = []
    for idx, decision_id in enumerate(decision_nodes):
        start_ts = decision_ts_by_idx.get(idx, 0.0)
        if start_ts <= 0:
            continue
        if idx > 0:
            newer_ts = decision_ts_by_idx.get(idx - 1, 0.0)
            end_ts = newer_ts if newer_ts > start_ts else (start_ts + 1.2)
        else:
            if snapshot_last_seen_ts > 0 and snapshot_last_seen_ts >= start_ts:
                end_ts = min(snapshot_last_seen_ts, now_ts)
            else:
                end_ts = min(now_ts, start_ts + 1.8)

        if set_node_live_window(decision_id, start_ts, end_ts, min_duration_sec=0.8):
            live_decision_nodes.append((decision_id, start_ts))
            decision_node = node_by_id.get(decision_id) or {}
            decision_idx = decision_node.get('meta', {}).get('decision_index')
            if isinstance(decision_idx, int):
                for n in nodes:
                    nid = str(n.get('id', ''))
                    if nid.startswith(f'reason:{decision_idx}:') or nid == f'signal:{decision_idx}':
                        set_node_live_window(nid, start_ts, end_ts, min_duration_sec=0.8)

    live_action_nodes = []
    for action_id, row, _abs_idx, _decision_id in action_nodes:
        start_ts = parse_any_ts(row.get('ts'))
        if start_ts <= 0:
            continue
        kind = str(row.get('kind', '')).lower()
        if kind == 'next_run':
            continue

        duration_sec = 0.0
        raw_duration_ms = row.get('duration_ms')
        if isinstance(raw_duration_ms, (int, float)) and raw_duration_ms > 0:
            duration_sec = float(raw_duration_ms) / 1000.0
            end_ts = start_ts + duration_sec
        elif kind in {'started', 'run'}:
            if snapshot_last_seen_ts > 0 and snapshot_last_seen_ts >= start_ts:
                end_ts = min(snapshot_last_seen_ts, now_ts)
            else:
                end_ts = min(now_ts, start_ts + 3.0)
            duration_sec = max(0.0, end_ts - start_ts)
        elif kind == 'finished':
            duration_sec = 1.2
            end_ts = start_ts + duration_sec
        else:
            duration_sec = 1.0
            end_ts = start_ts + duration_sec

        if set_node_live_window(action_id, start_ts, end_ts, min_duration_sec=1.0):
            live_action_nodes.append((action_id, start_ts))

    for action_id, row, abs_idx, _decision_id in action_nodes:
        outcome_id = f'outcome:{abs_idx}'
        start_ts = parse_any_ts(row.get('ts'))
        if start_ts <= 0:
            continue
        kind = str(row.get('kind', '')).lower()
        if kind == 'next_run':
            continue

        raw_duration_ms = row.get('duration_ms')
        if isinstance(raw_duration_ms, (int, float)) and raw_duration_ms > 0:
            duration_sec = float(raw_duration_ms) / 1000.0
            end_ts = start_ts + duration_sec
        else:
            duration_sec = 1.2
            end_ts = start_ts + duration_sec
        set_node_live_window(outcome_id, start_ts, end_ts, min_duration_sec=0.9)

    trigger_id = None
    if live_action_nodes:
        latest_action_id, _ = max(live_action_nodes, key=lambda item: item[1])
        trigger_id = latest_action_id
    elif live_decision_nodes:
        trigger_id, _ = max(live_decision_nodes, key=lambda item: item[1])
    elif live_activation_nodes:
        trigger_id, _ = max(live_activation_nodes, key=lambda item: item[1])

    if trigger_id is None:
        start_ts = parse_any_ts(snapshot.get('last_seen'))
        if start_ts > 0 and (now_ts - start_ts) <= max_live_from_start_sec:
            if set_node_live(agent_node, start_ts, 0.8):
                trigger_id = agent_node

    if trigger_id and trigger_id in node_by_id:
        node_by_id[trigger_id].setdefault('meta', {})['trigger_source'] = True

    live_ids = {str(n.get('id', '')) for n in nodes if n.get('meta', {}).get('live')}
    for edge in edges:
        source = str(edge.get('source', ''))
        target = str(edge.get('target', ''))
        edge_meta = edge.setdefault('meta', {})
        source_live = source in live_ids
        target_live = target in live_ids
        source_trigger = bool((node_by_id.get(source) or {}).get('meta', {}).get('trigger_source'))
        edge_meta['live'] = bool((source_live and target_live) or (source_trigger and target_live))

    return {
        'nodes': nodes,
        'edges': edges,
        'meta': {
            'generated_at_ts': now_ts,
            'max_activations': effective_max_activations,
            'activations_shown': len(activation_nodes_by_id),
            'outcomes_shown': len(outcome_source_nodes),
        },
    }


def fmt_seconds(seconds):
    """Format duration in seconds to compact human-readable string."""
    if seconds < 60:
        return f'{seconds}s'
    minutes = seconds // 60
    if minutes < 60:
        return f'{minutes}m'
    hours = minutes // 60
    return f'{hours}h'


def fmt_ts_ms(ms):
    """Format epoch milliseconds to local timestamp text."""
    if not isinstance(ms, (int, float)) or ms <= 0:
        return ''
    return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(ms / 1000))


def decode_json_stream(payload):
    """Decode multiple adjacent JSON objects from a possibly concatenated stream."""
    if not isinstance(payload, str):
        return []
    decoder = json.JSONDecoder()
    idx = 0
    out = []
    length = len(payload)
    while idx < length:
        while idx < length and payload[idx].isspace():
            idx += 1
        if idx >= length:
            break
        try:
            obj, end = decoder.raw_decode(payload, idx)
            out.append(obj)
            idx = end
        except Exception:
            idx += 1
    return out


def load_recent_cron_runs(job_id, max_items=8):
    """Load recent cron run events from job-specific JSONL logs."""
    path = os.path.join(CRON_RUNS_DIR, f'{job_id}.jsonl')
    if not os.path.exists(path):
        return []
    chunks = []
    try:
        with open(path, 'r', encoding='utf-8') as rf:
            tail_lines = deque(rf, maxlen=max_items)
        joined = '\n'.join([ln.strip() for ln in tail_lines if ln.strip()])
        chunks = decode_json_stream(joined)
    except Exception:
        return []
    events = [e for e in chunks if isinstance(e, dict)]
    return events[-max_items:]


def parse_message_actor(message):
    """Identify actor role from compact prefixed message text."""
    if not isinstance(message, str):
        return 'unknown', ''
    clean = message.strip()
    low = clean.lower()
    if low.startswith('user:'):
        return 'user', clean[5:].strip()
    if low.startswith('assistant:'):
        return 'assistant', clean[10:].strip()
    if low.startswith('toolresult:'):
        return 'tool', clean[11:].strip()
    return 'system', clean


def remember_interaction_key(key):
    """Remember an interaction key in a bounded dedupe cache.
    Returns True when key is new and should be accepted.
    """
    if not key:
        return False
    if key in interaction_seen_set:
        return False
    if len(interaction_seen_order) >= interaction_seen_order.maxlen:
        oldest = interaction_seen_order.popleft()
        interaction_seen_set.discard(oldest)
    interaction_seen_order.append(key)
    interaction_seen_set.add(key)
    return True


def detect_agent_mentions(text, source_agent):
    """Detect runtime-known agent mentions in text for agent-to-agent interaction inference."""
    if not isinstance(text, str):
        return []

    source_norm = normalize_agent_name(source_agent)
    known_by_norm = {}
    for row in agent_state.values():
        if not isinstance(row, dict):
            continue
        display = str(row.get('agent') or '').strip()
        norm = normalize_agent_name(display)
        if not norm:
            continue
        known_by_norm.setdefault(norm, display)

    if not known_by_norm:
        return []

    mentioned = []
    seen = set()
    low = text.lower()
    for norm_name, display_name in known_by_norm.items():
        if norm_name == source_norm:
            continue
        if re.search(rf'(?<![a-z0-9_]){re.escape(norm_name)}(?![a-z0-9_])', low):
            key = normalize_agent_name(display_name)
            if key in seen:
                continue
            seen.add(key)
            mentioned.append(display_name)
    return mentioned


def push_interaction(event):
    """Push inferred interaction events into rolling in-memory interaction queues."""
    agent = event.get('agent', 'unknown')
    messages = event.get('recent_messages') or []
    if not isinstance(messages, list) or not messages:
        return

    for message in messages[-2:]:
        actor, text = parse_message_actor(str(message))
        text_clamped = text[:420]
        mentions = detect_agent_mentions(text, agent)
        row = {
            'ts': event.get('last_seen') or utc_now_iso(),
            'agent': agent,
            'actor': actor,
            'text': text_clamped,
            'mentions': mentions,
        }
        if actor == 'user':
            key = f"ua|{normalize_agent_name(agent)}|{actor}|{text_clamped.strip().lower()}"
            if remember_interaction_key(key):
                recent_user_agent.appendleft(row)
        elif actor in {'assistant', 'system'} and mentions:
            for target in mentions:
                key = f"aa|{normalize_agent_name(agent)}|{normalize_agent_name(target)}|{text_clamped.strip().lower()}"
                if remember_interaction_key(key):
                    recent_agent_agent.appendleft({
                        'ts': row['ts'],
                        'source': agent,
                        'target': target,
                        'text': row['text'],
                    })


def build_cron_details(payloads):
    """Build detailed cron telemetry rows grouped by agent."""
    global cron_details_by_agent, cron_summary

    cron_payload = payloads.get('cron') or {}
    jobs = cron_payload.get('jobs') if isinstance(cron_payload, dict) else []
    jobs = jobs if isinstance(jobs, list) else []

    details_by_agent = {}
    next_candidates = []
    last_errors = []

    for job in jobs:
        if not isinstance(job, dict):
            continue
        agent_id = str(job.get('agentId') or '').strip().lower()
        if not agent_id:
            continue
        state = job.get('state') if isinstance(job.get('state'), dict) else {}
        next_run_ms = state.get('nextRunAtMs')
        last_run_ms = state.get('lastRunAtMs')
        last_status = state.get('lastStatus') or 'unknown'
        duration_ms = state.get('lastDurationMs')
        enabled = bool(job.get('enabled', True))

        run_entries = load_recent_cron_runs(job.get('id', ''), max_items=6)
        last_entry = run_entries[-1] if run_entries else {}
        interrupted = last_status not in {'ok', 'success'}

        row = {
            'job_id': job.get('id', ''),
            'name': job.get('name', 'cron-job'),
            'enabled': enabled,
            'schedule_kind': (job.get('schedule') or {}).get('kind', 'unknown') if isinstance(job.get('schedule'), dict) else 'unknown',
            'every_ms': (job.get('schedule') or {}).get('everyMs') if isinstance(job.get('schedule'), dict) else None,
            'next_run_ms': next_run_ms,
            'next_run_at': fmt_ts_ms(next_run_ms),
            'last_run_ms': last_run_ms,
            'last_run_at': fmt_ts_ms(last_run_ms),
            'last_status': last_status,
            'last_duration_ms': duration_ms,
            'interrupted': interrupted,
            'summary': (last_entry or {}).get('summary') or ((job.get('payload') or {}).get('text') if isinstance(job.get('payload'), dict) else ''),
            'next_action': ((job.get('payload') or {}).get('text') if isinstance(job.get('payload'), dict) else '')[:220],
            'wake_mode': job.get('wakeMode', ''),
            'session_target': job.get('sessionTarget', ''),
            'recent_runs': run_entries,
        }

        details_by_agent.setdefault(agent_id.capitalize(), []).append(row)
        if enabled and isinstance(next_run_ms, (int, float)):
            next_candidates.append({'agent': agent_id.capitalize(), 'name': row['name'], 'next_run_ms': next_run_ms, 'next_run_at': row['next_run_at']})
        if interrupted:
            last_errors.append({'agent': agent_id.capitalize(), 'name': row['name'], 'status': last_status, 'summary': row['summary']})

    next_candidates.sort(key=lambda x: x.get('next_run_ms') or float('inf'))
    cron_details_by_agent = details_by_agent
    cron_summary = {
        'active_jobs': sum(1 for jobs in details_by_agent.values() for j in jobs if j.get('enabled')),
        'next_up': next_candidates[:8],
        'last_errors': last_errors[:8],
    }


def run_openclaw_json(args):  # pragma: no cover
    """Execute OpenClaw CLI command and parse JSON output safely."""
    if shutil.which('openclaw') is None:
        return None
    try:
        cmd = ['openclaw'] + args + ['--json']
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=8)
        if res.returncode != 0:
            return None
        payload = (res.stdout or '').strip()
        if not payload:
            return None
        return json.loads(payload)
    except Exception:
        return None


def compute_core_capabilities(payloads):
    """Update capability flags based on latest core payload availability."""
    CORE_CAPABILITIES['openclaw_cli'] = bool(shutil.which('openclaw'))
    CORE_CAPABILITIES['channels']['agents_list'] = isinstance(payloads.get('agents'), list)
    CORE_CAPABILITIES['channels']['cron_list'] = isinstance(payloads.get('cron', {}).get('jobs'), list)
    CORE_CAPABILITIES['channels']['status'] = isinstance(payloads.get('status'), dict)
    presence_payload = payloads.get('presence')
    CORE_CAPABILITIES['channels']['presence'] = isinstance(presence_payload, list) or isinstance(presence_payload, dict)


def build_core_agent_states(payloads):
    """Build agent snapshots from OpenClaw core payloads only (passive mode)."""
    agents_payload = payloads.get('agents') or []
    cron_payload = payloads.get('cron') or {}
    status_payload = payloads.get('status') or {}

    jobs = cron_payload.get('jobs') if isinstance(cron_payload, dict) else []
    jobs = jobs if isinstance(jobs, list) else []
    jobs_by_agent = {}
    for job in jobs:
        if not isinstance(job, dict):
            continue
        agent_id = str(job.get('agentId') or '').strip().lower()
        if not agent_id:
            continue
        jobs_by_agent.setdefault(agent_id, []).append(job)

    recent_sessions = status_payload.get('sessions', {}).get('recent', []) if isinstance(status_payload, dict) else []
    recent_by_agent = {}
    for entry in recent_sessions:
        if not isinstance(entry, dict):
            continue
        agent_id = str(entry.get('agentId') or '').strip().lower()
        if not agent_id:
            continue
        existing = recent_by_agent.get(agent_id)
        if existing is None or entry.get('updatedAt', 0) > existing.get('updatedAt', 0):
            recent_by_agent[agent_id] = entry

    now_ms = int(time.time() * 1000)
    result = []
    for item in agents_payload:
        if not isinstance(item, dict):
            continue
        agent_id = str(item.get('id') or '').strip().lower()
        if not agent_id:
            continue
        display_agent = item.get('name') or agent_id.capitalize()
        agent_jobs = jobs_by_agent.get(agent_id, [])
        enabled_jobs = [j for j in agent_jobs if j.get('enabled', True)]
        mission_names = [j.get('name', '') for j in enabled_jobs if j.get('name')][:4]
        job_rows = cron_details_by_agent.get(display_agent, [])

        next_run_ms = None
        for job in enabled_jobs:
            state = job.get('state') if isinstance(job.get('state'), dict) else {}
            candidate = state.get('nextRunAtMs')
            if isinstance(candidate, (int, float)) and candidate > 0:
                next_run_ms = candidate if next_run_ms is None else min(next_run_ms, candidate)

        recent = recent_by_agent.get(agent_id)
        recent_messages = []
        status = 'Idle'
        task = 'Waiting for next core event'
        last_seen = utc_now_iso()

        if isinstance(recent, dict):
            age_ms = int(recent.get('age') or 0)
            updated_at = recent.get('updatedAt')
            if isinstance(updated_at, (int, float)) and updated_at > 0:
                last_seen = time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(updated_at / 1000))
            if age_ms <= 300000:
                status = 'Active'
                task = 'Recent session activity detected'
            else:
                status = 'Observed'
                task = 'No recent session activity detected'
            model = recent.get('model') or 'n/a'
            total_tokens = recent.get('totalTokens')
            if isinstance(total_tokens, (int, float)):
                recent_messages.append(f'session: model={model}, tokens={int(total_tokens)}')
            else:
                recent_messages.append(f'session: model={model}')

        if next_run_ms is not None:
            delta_sec = max(0, int((next_run_ms - now_ms) / 1000))
            next_text = fmt_seconds(delta_sec)
            task = f'Next cron run in {next_text}'
            if delta_sec <= 120:
                status = 'Active'

        interrupted_jobs = [j for j in job_rows if j.get('interrupted')]
        if interrupted_jobs:
            status = 'Attention'
            task = f"{len(interrupted_jobs)} cron jobs are non-ok"

        result.append({
            'agent': display_agent,
            'status': status,
            'task': task,
            'last_seen': last_seen,
            'cron_jobs': len(enabled_jobs),
            'active_missions': mission_names,
            'cpu': '',
            'mem': '',
            'recent_messages': recent_messages,
            'recent_thoughts': [],
            'current_thought': '',
            'cron_details': job_rows,
            'interrupted_tasks': interrupted_jobs,
            'real_time': True,
            'raw': {
                'source': 'openclaw-core',
                'agentId': agent_id,
                'mode': OPENCLAW_MODE,
                'confidence': 'high',
                'model': (recent or {}).get('model') if isinstance(recent, dict) else None,
                'totalTokens': (recent or {}).get('totalTokens') if isinstance(recent, dict) else None,
                'inputTokens': (recent or {}).get('inputTokens') if isinstance(recent, dict) else None,
                'outputTokens': (recent or {}).get('outputTokens') if isinstance(recent, dict) else None,
                'contextTokens': (recent or {}).get('contextTokens') if isinstance(recent, dict) else None,
                'updatedAt': (recent or {}).get('updatedAt') if isinstance(recent, dict) else None,
                'age': (recent or {}).get('age') if isinstance(recent, dict) else None,
                'memory': item.get('memory') if isinstance(item, dict) else None,
                'mem': item.get('mem') if isinstance(item, dict) else None,
                'rss': item.get('rss') if isinstance(item, dict) else None,
            },
        })
    return result


def fetch_core_payloads():  # pragma: no cover
    """Collect all relevant core telemetry payloads in one polling cycle."""
    return {
        'agents': run_openclaw_json(['agents', 'list']),
        'cron': run_openclaw_json(['cron', 'list']),
        'status': run_openclaw_json(['status']),
        'presence': run_openclaw_json(['system', 'presence']),
    }


def apply_core_snapshot(states):
    """Merge and emit core-derived snapshots into global state and sockets."""
    global BUS_READY
    if not isinstance(states, list):
        return

    init_needed = False
    changed_payloads = []
    with state_lock:
        if not agent_state:
            init_needed = True

        for current in states:
            agent = current.get('agent')
            if not agent:
                continue
            previous = agent_state.get(agent, {})
            merged = previous.copy()

            merged['agent'] = current.get('agent', merged.get('agent', 'unknown'))
            merged['cron_jobs'] = current.get('cron_jobs', merged.get('cron_jobs', 0))
            merged['active_missions'] = current.get('active_missions', merged.get('active_missions', []))
            merged['last_seen'] = current.get('last_seen', merged.get('last_seen', utc_now_iso()))
            merged['real_time'] = True
            merged['raw_core'] = current.get('raw', {})
            merged['cron_details'] = current.get('cron_details', merged.get('cron_details', []))
            merged['interrupted_tasks'] = current.get('interrupted_tasks', merged.get('interrupted_tasks', []))

            if OPENCLAW_MODE == 'core-only-passive':
                merged['status'] = current.get('status', merged.get('status', 'Observed'))
                merged['task'] = current.get('task', merged.get('task', ''))
                merged['recent_messages'] = current.get('recent_messages', [])
                merged['recent_thoughts'] = []
                merged['current_thought'] = ''
                merged['raw'] = current.get('raw', {})
            else:
                if not merged.get('status') or merged.get('status') == 'unknown':
                    merged['status'] = current.get('status', 'Observed')
                if not merged.get('task'):
                    merged['task'] = current.get('task', '')
                if not merged.get('recent_messages') and current.get('recent_messages'):
                    merged['recent_messages'] = current.get('recent_messages', [])

            if merged != previous:
                agent_state[agent] = merged
                changed_payloads.append(merged)
                push_interaction(merged)

        if states and not BUS_READY:
            BUS_READY = True

    if init_needed:
        with state_lock:
            snapshot = list(agent_state.values())
        socketio.emit('init', snapshot)
    else:
        for payload in changed_payloads:
            socketio.emit('update', payload)


def core_only_monitor():  # pragma: no cover
    """Background passive monitor that refreshes state from OpenClaw core CLI."""
    global BUS_READY
    print('[CORE] OpenClaw core monitor started')
    while True:
        try:
            payloads = fetch_core_payloads()
            compute_core_capabilities(payloads)
            build_cron_details(payloads)
            states = build_core_agent_states(payloads)
            apply_core_snapshot(states)
            if states and not BUS_READY:
                BUS_READY = True
        except Exception as e:
            print(f'[CORE] monitor error: {e}')
        time.sleep(max(1.0, CORE_POLL_INTERVAL_SEC))


def ensure_bus_reader_started():  # pragma: no cover
    """Thread-safe bootstrap for background readers/monitors."""
    with bootstrap_lock:
        start_bus_reader()


def append_event_to_bus(event):  # pragma: no cover
    """Append a normalized event into the shared event bus JSONL file."""
    try:
        os.makedirs(os.path.dirname(BUS_PATH), exist_ok=True)
        with open(BUS_PATH, 'a', encoding='utf-8') as bf:
            bf.write(json.dumps(event, ensure_ascii=False) + '\n')
    except Exception as e:
        print(f'[BRIDGE] Failed to append event to bus: {e}')


def get_text_from_content_block(block, key):  # pragma: no cover
    """Extract a text field from one structured content block."""
    value = block.get(key)
    if not value:
        return ''
    if isinstance(value, str):
        return value.strip()
    return ''


def extract_session_event(agent_name, entry):  # pragma: no cover
    """Convert a session entry into a dashboard-ready event."""
    message = entry.get('message') or {}
    role = (message.get('role') or '').strip().lower()
    if role not in {'user', 'assistant'}:
        return None
    content = message.get('content')
    if not isinstance(content, list):
        return None

    text_chunks = []
    thought_chunks = []
    for block in content:
        if not isinstance(block, dict):
            continue
        block_type = (block.get('type') or '').strip().lower()
        if block_type == 'text':
            text_value = get_text_from_content_block(block, 'text')
            if text_value:
                text_chunks.append(text_value)
        elif block_type == 'thinking':
            thought_value = get_text_from_content_block(block, 'thinking')
            if thought_value:
                thought_chunks.append(thought_value)

    if not text_chunks and not thought_chunks:
        return None

    text_preview = (' '.join(text_chunks)).replace('\n', ' ').strip()
    thought_preview = (' '.join(thought_chunks)).replace('\n', ' ').strip()

    recent_messages = []
    if text_preview:
        prefix = role if role else 'agent'
        recent_messages = [f'{prefix}: {text_preview[:240]}']

    recent_thoughts = []
    current_thought = ''
    if thought_preview:
        recent_thoughts = [thought_preview[:240]]
        current_thought = recent_thoughts[0]

    timestamp = entry.get('timestamp') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())
    if role == 'user':
        task = 'User interaction'
    else:
        task = 'Agent response'

    return {
        'agent': agent_name,
        'source': 'session-bridge',
        'type': 'session_update',
        'status': 'Active',
        'task': task,
        'ts': timestamp,
        'recent_messages': recent_messages,
        'recent_thoughts': recent_thoughts,
        'current_thought': current_thought,
        'real_time': True,
    }


def session_entry_dedupe_key(entry):  # pragma: no cover
    """Compute a stable dedupe key for session entries.
    Uses native id when available, otherwise hashes timestamp+role+content.
    """
    if not isinstance(entry, dict):
        return ''
    entry_id = entry.get('id')
    if entry_id:
        return f"id:{entry_id}"
    message = entry.get('message') if isinstance(entry.get('message'), dict) else {}
    payload = {
        'timestamp': entry.get('timestamp') or '',
        'role': message.get('role') or '',
        'content': message.get('content') or [],
    }
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return f"hash:{hashlib.sha1(raw.encode('utf-8')).hexdigest()}"


def list_agent_session_files():  # pragma: no cover
    """Find latest session JSONL file per agent."""
    files = {}
    try:
        agent_dirs = [d for d in os.listdir(AGENTS_ROOT) if os.path.isdir(os.path.join(AGENTS_ROOT, d))]
    except Exception:
        return files

    for agent_dir_name in agent_dirs:
        sessions_dir = os.path.join(AGENTS_ROOT, agent_dir_name, 'sessions')
        if not os.path.isdir(sessions_dir):
            continue
        try:
            jsonl_files = [
                os.path.join(sessions_dir, name)
                for name in os.listdir(sessions_dir)
                if name.endswith('.jsonl')
            ]
        except Exception:
            continue
        if not jsonl_files:
            continue
        latest_file = max(jsonl_files, key=lambda p: os.path.getmtime(p))
        display_name = agent_dir_name.capitalize()
        files[display_name] = latest_file
    return files


def load_last_session_lines(file_path, max_entries=2):  # pragma: no cover
    """Load tail entries from a session file, tolerant to malformed lines."""
    entries = []
    try:
        with open(file_path, 'r', encoding='utf-8') as sf:
            tail_lines = deque(sf, maxlen=max_entries)
        for line in tail_lines:
            raw = line.strip()
            if not raw:
                continue
            try:
                entries.append(json.loads(raw))
            except Exception:
                continue
    except Exception:
        return []
    return entries


def bridge_sessions_to_bus():  # pragma: no cover
    """Continuously mirror session JSONL updates into the shared bus stream."""
    print('[BRIDGE] Session->bus bridge started')
    file_offsets = {}
    seen_ids = set()

    while True:
        try:
            latest_files = list_agent_session_files()
            for agent_name, file_path in latest_files.items():
                previous = file_offsets.get(agent_name)
                if previous is None or previous.get('path') != file_path:
                    bootstrap_entries = load_last_session_lines(file_path, max_entries=4)
                    for entry in bootstrap_entries:
                        entry_key = session_entry_dedupe_key(entry)
                        if entry_key and entry_key in seen_ids:
                            continue
                        event = extract_session_event(agent_name, entry)
                        if event:
                            append_event_to_bus(event)
                        if entry_key:
                            seen_ids.add(entry_key)
                    file_offsets[agent_name] = {
                        'path': file_path,
                        'offset': os.path.getsize(file_path),
                    }
                    continue

                current_offset = previous.get('offset', 0)
                file_size = os.path.getsize(file_path)
                if file_size < current_offset:
                    current_offset = 0

                if file_size > current_offset:
                    with open(file_path, 'r', encoding='utf-8') as sf:
                        sf.seek(current_offset)
                        for line in sf:
                            raw = line.strip()
                            if not raw:
                                continue
                            try:
                                entry = json.loads(raw)
                            except Exception:
                                continue
                            entry_key = session_entry_dedupe_key(entry)
                            if entry_key and entry_key in seen_ids:
                                continue
                            event = extract_session_event(agent_name, entry)
                            if event:
                                append_event_to_bus(event)
                            if entry_key:
                                seen_ids.add(entry_key)
                        file_offsets[agent_name]['offset'] = sf.tell()

            if len(seen_ids) > 5000:
                seen_ids = set(list(seen_ids)[-1000:])
        except Exception as e:
            print(f'[BRIDGE] Session bridge error: {e}')

        time.sleep(1.0)


@app.before_request
def bootstrap_before_request():  # pragma: no cover
    """Ensure background readers are started before handling requests."""
    ensure_bus_reader_started()

@socketio.on('connect')
def handle_connect():  # pragma: no cover
    """Handle new websocket client connections and push initial state."""
    print("Client connected")
    sid = request.sid
    ensure_bus_reader_started()
    # Wait for the background reader to populate state (avoid emitting a misleading 'unknown' placeholder)
    waited = 0.0
    data = []
    while waited < 3.0:
        with state_lock:
            data = list(agent_state.values())
        if BUS_READY:
            break
        time.sleep(0.25)
        waited += 0.25
    # If still not ready, emit a short pending message and return (client will retry)
    if not BUS_READY:
        print('[DEBUG] Client connected before BUS_READY; emitting init_pending')
        socketio.emit('init_pending', {'msg': 'server_not_ready'}, room=sid)
        return
    # Emit populated state
    print(f'[DEBUG] Emitting init to new client: {data}')
    socketio.emit('init', data, room=sid)

@socketio.on('init_request')
def handle_init_request():  # pragma: no cover
    """Handle explicit init retry request sent by frontend bootstrap logic."""
    sid = request.sid
    ensure_bus_reader_started()
    with state_lock:
        data = list(agent_state.values())
    if not BUS_READY:
        socketio.emit('init_pending', {'msg': 'server_not_ready'}, room=sid)
    else:
        socketio.emit('init', data, room=sid)

@socketio.on('disconnect')
def handle_disconnect():  # pragma: no cover
    """Log websocket disconnect events."""
    print("Client disconnected")


def archive_invalid_line(line):  # pragma: no cover
    """Persist malformed bus lines for offline diagnostics."""
    try:
        os.makedirs(INVALID_DIR, exist_ok=True)
        ts = int(time.time())
        path = os.path.join(INVALID_DIR, f'invalid.{ts}.log')
        with open(path, 'a', encoding='utf-8') as af:
            af.write(line + '\n')
        print(f'[BUS] Archived invalid line to {path}')
    except Exception as e:
        print(f'[BUS] Failed to archive invalid line: {e}')


def tail_bus(path):  # pragma: no cover
    """Tail a JSONL event bus file and emit updates to connected websocket clients.
    Each line must be a JSON object with at least an 'agent' and 'status' field.
    On start, reads the full file to populate initial state and emits an 'init'.
    """
    global BUS_READY
    print(f'[BUS] Starting tail on {path} (pid={os.getpid()}, ppid={os.getppid()})')
    # Ensure file exists
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
    except Exception:
        pass
    # If file doesn't exist yet, create it
    if not os.path.exists(path):
        open(path, 'a').close()

    # First pass: read entire file to build initial state
    initial_events = []
    with open(path, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception as e:
                print(f'[BUS] Failed to parse historical line: {line} -> {e}')
                archive_invalid_line(line)
                continue
            if should_skip_event(event):
                continue
            normalized = normalize_event(event)
            agent = normalized['agent']
            initial_events.append((agent, normalized))

    # Populate in-memory state
    with state_lock:
        for agent, normalized in initial_events:
            if agent == 'unknown':
                # skip unknown entries coming from legacy/system rows
                continue
            # initialize histories if missing
            normalized.setdefault('message_history', [])
            normalized.setdefault('thought_history', [])
            if normalized.get('cron_jobs') is None:
                normalized['cron_jobs'] = 0
            if normalized.get('active_missions') is None:
                normalized['active_missions'] = []
            if normalized.get('cpu') is None:
                normalized['cpu'] = ''
            if normalized.get('mem') is None:
                normalized['mem'] = ''
            if normalized.get('recent_messages') is None:
                normalized['recent_messages'] = []
            if normalized.get('recent_thoughts') is None:
                normalized['recent_thoughts'] = []
            if normalized.get('current_thought') is None:
                normalized['current_thought'] = ''
            # try to load persisted history file
            os.makedirs(HISTORY_DIR, exist_ok=True)
            history_path = os.path.join(HISTORY_DIR, f"{agent}.jsonl")
            if os.path.exists(history_path):
                try:
                    with open(history_path, 'r', encoding='utf-8') as hf:
                        for hline in hf:
                            try:
                                entry = json.loads(hline.strip())
                                if entry.get('type') == 'message':
                                    text = str(entry.get('text') or '').strip()
                                    recent = normalized['message_history'][-40:]
                                    if text and any(str(e.get('text') or '').strip() == text for e in recent):
                                        continue
                                    normalized['message_history'].append(entry)
                                elif entry.get('type') == 'thought':
                                    text = str(entry.get('text') or '').strip()
                                    recent = normalized['thought_history'][-40:]
                                    if text and any(str(e.get('text') or '').strip() == text for e in recent):
                                        continue
                                    normalized['thought_history'].append(entry)
                            except Exception:
                                continue
                except Exception:
                    pass
            agent_state[agent] = normalized
    # Emit init only if we have entries
    def is_system_event(v):
        raw = v.get('raw', {})
        if raw.get('from') == 'system':
            return True
        if raw.get('type') == 'announcement':
            return True
        return False

    data = [v for v in agent_state.values() if v.get('agent') != 'unknown' and not is_system_event(v)]
    # Avoid excessively noisy repeated initial-emits in logs (process may be forked)
    try:
        if not globals().get('_emitted_initial_once'):
            print(f'[BUS] Emitting initial full state to clients: {data}')
            globals()['_emitted_initial_once'] = True
        else:
            print('[BUS] Emitting initial full state to clients (suppressed verbose payload)')
    except Exception:
        print('[BUS] Emitting initial full state to clients')
    socketio.emit('init', data)
    BUS_READY = True

    # Now tail for new events
    with open(path, 'r', encoding='utf-8') as f:
        # Seek to end to only read new events
        f.seek(0, os.SEEK_END)
        while True:
            line = f.readline()
            if not line:
                time.sleep(0.5)
                continue
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except Exception as e:
                print(f'[BUS] Failed to parse line: {line} -> {e}')
                archive_invalid_line(line)
                continue
            if should_skip_event(event):
                continue
            normalized = normalize_event(event)
            agent = normalized['agent']
            # merge into existing state and maintain histories
            with state_lock:
                prev = agent_state.get(agent, {})
                # init histories
                mh = prev.get('message_history', [])[:]
                th = prev.get('thought_history', [])[:]
                # append recent messages/thoughts from event (if present)
                for m in event.get('recent_messages', []):
                    entry = {'type': 'message', 'ts': event.get('ts') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'text': m}
                    text = str(m or '').strip()
                    if text and any(str(e.get('text') or '').strip() == text for e in mh[-40:]):
                        continue
                    mh.append(entry)
                    # persist
                    try:
                        os.makedirs(HISTORY_DIR, exist_ok=True)
                        history_path = os.path.join(HISTORY_DIR, f"{agent}.jsonl")
                        with open(history_path, 'a', encoding='utf-8') as hf:
                            hf.write(json.dumps(entry) + '\n')
                    except Exception:
                        pass
                for t in event.get('recent_thoughts', []):
                    entry = {'type': 'thought', 'ts': event.get('ts') or time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()), 'text': t}
                    text = str(t or '').strip()
                    if text and any(str(e.get('text') or '').strip() == text for e in th[-40:]):
                        continue
                    th.append(entry)
                    try:
                        os.makedirs(HISTORY_DIR, exist_ok=True)
                        history_path = os.path.join(HISTORY_DIR, f"{agent}.jsonl")
                        with open(history_path, 'a', encoding='utf-8') as hf:
                            hf.write(json.dumps(entry) + '\n')
                    except Exception:
                        pass
                # cap histories to 200
                mh = mh[-200:]
                th = th[-200:]
                merged = prev.copy()
                merged['agent'] = normalized.get('agent', merged.get('agent', 'unknown'))
                merged['status'] = normalized.get('status', merged.get('status', 'unknown'))
                merged['task'] = normalized.get('task', merged.get('task', ''))
                merged['last_seen'] = normalized.get('last_seen', merged.get('last_seen', utc_now_iso()))
                if normalized.get('cron_jobs') is not None:
                    merged['cron_jobs'] = normalized.get('cron_jobs')
                else:
                    merged.setdefault('cron_jobs', 0)
                if normalized.get('active_missions') is not None:
                    merged['active_missions'] = normalized.get('active_missions')
                else:
                    merged.setdefault('active_missions', [])
                if normalized.get('cpu') is not None:
                    merged['cpu'] = normalized.get('cpu')
                else:
                    merged.setdefault('cpu', '')
                if normalized.get('mem') is not None:
                    merged['mem'] = normalized.get('mem')
                else:
                    merged.setdefault('mem', '')
                if normalized.get('recent_messages') is not None:
                    merged['recent_messages'] = normalized.get('recent_messages')
                else:
                    merged.setdefault('recent_messages', [])
                if normalized.get('recent_thoughts') is not None:
                    merged['recent_thoughts'] = normalized.get('recent_thoughts')
                else:
                    merged.setdefault('recent_thoughts', [])
                if normalized.get('current_thought') is not None:
                    merged['current_thought'] = normalized.get('current_thought')
                else:
                    merged.setdefault('current_thought', '')

                merged['real_time'] = normalized.get('real_time', True)
                merged['raw'] = normalized.get('raw', {})
                merged['message_history'] = mh
                merged['thought_history'] = th

                if prev.get('task') and prev.get('task') != merged.get('task'):
                    merged['interrupted_task'] = prev.get('task')

                if merged.get('cron_details') is None:
                    merged['cron_details'] = []

                agent_state[agent] = merged
                push_interaction(merged)
            print(f'[BUS] Emitting update for {agent}: {merged}')
            socketio.emit('update', merged)


def start_bus_reader():  # pragma: no cover
    """Start bus reader, session bridge, and optional core monitor based on mode."""
    global bus_reader_started, session_bridge_started, core_monitor_started

    print(f'[BUS] start_bus_reader invoked (pid={os.getpid()}, ppid={os.getppid()})')

    if OPENCLAW_MODE not in {'legacy', 'core-only-passive', 'auto'}:
        print(f'[BOOT] Unknown AGENT_DASHBOARD_MODE={OPENCLAW_MODE}, fallback to auto behavior')

    if OPENCLAW_MODE in {'auto', 'core-only-passive'} and not core_monitor_started:
        core_monitor_started = True
        threading.Thread(target=core_only_monitor, daemon=True).start()

    if OPENCLAW_MODE == 'core-only-passive':
        if not BUS_READY:
            print('[BOOT] core-only-passive enabled, waiting for core monitor bootstrap')
        return

    if bus_reader_started:
        print('[BUS] Reader already started in this process, skipping')
        return
    bus_reader_started = True
    print(f'[BUS] Acquired lock and starting bus reader, pid={os.getpid()}, ppid={os.getppid()}')
    threading.Thread(target=tail_bus, args=(BUS_PATH,), daemon=True).start()
    if not session_bridge_started:
        session_bridge_started = True
        threading.Thread(target=bridge_sessions_to_bus, daemon=True).start()


if __name__ == '__main__':  # pragma: no cover
    if os.environ.get('AGENT_DASHBOARD_DISABLE_INTERNAL_READER') != '1':
        start_bus_reader()
    else:
        print('[BUS] Internal reader disabled by AGENT_DASHBOARD_DISABLE_INTERNAL_READER=1')
    socketio.run(app, host='0.0.0.0', port=5050, debug=True, allow_unsafe_werkzeug=True)
