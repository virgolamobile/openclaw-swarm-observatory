import app as dashboard_app
import time
import tempfile
import os
import builtins


def test_should_skip_event_filters_system_and_invalid_rows():
    assert dashboard_app.should_skip_event({"from": "system", "type": "announcement"}) is True
    assert dashboard_app.should_skip_event({"type": "heartbeat"}) is True
    assert dashboard_app.should_skip_event({"source": "Mercurio", "status": "ok"}) is False
    assert dashboard_app.should_skip_event({"agent": "Europa", "status": "active"}) is False


def test_normalize_event_produces_expected_schema():
    event = {
        "agent": "Mercurio",
        "status": "Active",
        "task": "Testing",
        "ts": "2026-02-12T12:00:00Z",
        "cron_jobs": 3,
        "active_missions": ["m1"],
        "cpu": "5%",
        "mem": "100MB",
        "recent_messages": ["hello"],
        "recent_thoughts": ["think"],
        "current_thought": "focus",
        "real_time": True,
    }

    normalized = dashboard_app.normalize_event(event)

    assert normalized["agent"] == "Mercurio"
    assert normalized["status"] == "Active"
    assert normalized["task"] == "Testing"
    assert normalized["last_seen"] == "2026-02-12T12:00:00Z"
    assert normalized["cron_jobs"] == 3
    assert normalized["active_missions"] == ["m1"]
    assert normalized["cpu"] == "5%"
    assert normalized["mem"] == "100MB"
    assert normalized["recent_messages"] == ["hello"]
    assert normalized["recent_thoughts"] == ["think"]
    assert normalized["current_thought"] == "focus"
    assert normalized["real_time"] is True
    assert normalized["raw"] == event


def test_normalize_event_keeps_optional_fields_as_none_when_absent():
    normalized = dashboard_app.normalize_event({"agent": "Europa", "status": "Active"})
    assert normalized["cron_jobs"] is None
    assert normalized["active_missions"] is None
    assert normalized["recent_messages"] is None
    assert normalized["recent_thoughts"] is None
    assert normalized["current_thought"] is None


def test_ready_endpoint_reflects_bus_ready_flag():
    client = dashboard_app.app.test_client()

    old_ready = dashboard_app.BUS_READY
    try:
        dashboard_app.BUS_READY = False
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.get_json() == {"ready": False}

        dashboard_app.BUS_READY = True
        response = client.get("/ready")
        assert response.status_code == 200
        assert response.get_json() == {"ready": True}
    finally:
        dashboard_app.BUS_READY = old_ready


def test_build_core_agent_states_maps_core_payloads():
    now_ms = int(time.time() * 1000)
    payloads = {
        "agents": [
            {"id": "mercurio", "name": "Mercurio"},
            {"id": "roma", "name": "Roma"},
        ],
        "cron": {
            "jobs": [
                {
                    "agentId": "mercurio",
                    "name": "heartbeat",
                    "enabled": True,
                    "state": {"nextRunAtMs": now_ms + 180000},
                }
            ]
        },
        "status": {
            "sessions": {
                "recent": [
                    {
                        "agentId": "mercurio",
                        "age": 120000,
                        "updatedAt": now_ms,
                        "model": "gpt",
                        "totalTokens": 123,
                    }
                ]
            }
        },
    }

    states = dashboard_app.build_core_agent_states(payloads)
    assert len(states) == 2

    mercurio = next(s for s in states if s["agent"] == "Mercurio")
    roma = next(s for s in states if s["agent"] == "Roma")

    assert mercurio["cron_jobs"] == 1
    assert mercurio["status"] in {"Active", "Observed"}
    assert mercurio["task"].startswith("Next cron run in")
    assert mercurio["recent_messages"]
    assert mercurio["raw"]["source"] == "openclaw-core"

    assert roma["cron_jobs"] == 0
    assert roma["recent_messages"] == []


def test_apply_core_snapshot_core_only_replaces_runtime_fields():
    old_mode = dashboard_app.OPENCLAW_MODE
    old_ready = dashboard_app.BUS_READY
    try:
        dashboard_app.OPENCLAW_MODE = "core-only-passive"
        dashboard_app.BUS_READY = False
        with dashboard_app.state_lock:
            dashboard_app.agent_state.clear()
            dashboard_app.agent_state["Mercurio"] = {
                "agent": "Mercurio",
                "status": "unknown",
                "task": "",
                "recent_thoughts": ["old"],
            }

        dashboard_app.apply_core_snapshot([
            {
                "agent": "Mercurio",
                "status": "Active",
                "task": "Prossimo cron tra 30s",
                "last_seen": "2026-02-12T12:00:00Z",
                "cron_jobs": 2,
                "active_missions": ["a"],
                "recent_messages": ["session: ok"],
                "raw": {"source": "openclaw-core"},
            }
        ])

        with dashboard_app.state_lock:
            merged = dashboard_app.agent_state["Mercurio"]
        assert merged["status"] == "Active"
        assert merged["task"] == "Prossimo cron tra 30s"
        assert merged["recent_thoughts"] == []
        assert merged["current_thought"] == ""
        assert merged["cron_jobs"] == 2
        assert merged["raw"]["source"] == "openclaw-core"
        assert dashboard_app.BUS_READY is True
    finally:
        dashboard_app.OPENCLAW_MODE = old_mode
        dashboard_app.BUS_READY = old_ready


def test_capabilities_endpoint_exposes_mode_and_tracking_count():
    client = dashboard_app.app.test_client()
    old_ready = dashboard_app.BUS_READY
    try:
        dashboard_app.BUS_READY = True
        with dashboard_app.state_lock:
            dashboard_app.agent_state.clear()
            dashboard_app.agent_state["Mercurio"] = {"agent": "Mercurio"}

        response = client.get("/capabilities")
        assert response.status_code == 200
        payload = response.get_json()
        assert payload["ready"] is True
        assert payload["tracked_agents"] == 1
        assert payload["capabilities"]["provider"] == "openclaw-cli"
    finally:
        dashboard_app.BUS_READY = old_ready


def test_insights_endpoint_returns_structured_payload():
    client = dashboard_app.app.test_client()
    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
        dashboard_app.agent_state["Europa"] = {
            "agent": "Europa",
            "status": "Active",
            "cron_jobs": 2,
        }

    response = client.get("/insights")
    assert response.status_code == 200
    payload = response.get_json()
    assert "generated_at" in payload
    assert "agents" in payload
    assert "interactions" in payload
    assert "cron" in payload
    assert isinstance(payload["agents"], list)


def test_infer_decision_trace_extracts_reason_links():
    timeline = [
        {
            "ts": "2026-02-12T12:01:00Z",
            "source": "realtime",
            "type": "recent_assistant",
            "text": "assistant: Il gateway è attivo e funzionante.",
        },
        {
            "ts": "2026-02-12T12:00:20Z",
            "source": "interaction",
            "type": "user_interaction",
            "text": "user: Controlla lo stato del gateway",
        },
    ]

    decisions = dashboard_app.infer_decision_trace("europa", timeline)
    assert decisions
    first = decisions[0]
    assert first["agent"] == "Europa"
    assert "Recent user request" in " ".join(first["why"])
    assert first["confidence"] in {"high", "medium"}


def test_drilldown_endpoint_returns_depth_layers_for_agent():
    client = dashboard_app.app.test_client()
    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
        dashboard_app.agent_state["Europa"] = {
            "agent": "Europa",
            "status": "Active",
            "task": "Verifica gateway",
            "last_seen": "2026-02-12T12:00:00Z",
            "cron_jobs": 2,
            "recent_messages": ["assistant: Gateway ok"],
            "recent_thoughts": ["controllo stato"],
            "message_history": [{"type": "message", "ts": "2026-02-12T11:59:00Z", "text": "user: check"}],
            "thought_history": [{"type": "thought", "ts": "2026-02-12T11:59:10Z", "text": "analisi"}],
            "cron_details": [
                {
                    "name": "Gateway watchdog",
                    "last_status": "ok",
                    "last_run_at": "2026-02-12 12:00:00",
                    "next_run_at": "2026-02-12 12:15:00",
                    "summary": "controllo salute",
                    "recent_runs": [],
                }
            ],
            "interrupted_tasks": [],
        }

    response = client.get("/drilldown/Europa")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["found"] is True
    assert payload["agent"] == "Europa"
    assert "depth" in payload
    assert "overview" in payload["depth"]
    assert "timeline" in payload["depth"]
    assert "decision_trace" in payload["depth"]
    assert "cron" in payload["depth"]


def test_build_cron_timeline_orders_events_and_includes_next_runs():
    now_ms = int(time.time() * 1000)
    items = dashboard_app.build_cron_timeline([
        {
            "name": "Heartbeat Europa",
            "next_run_ms": now_ms + 60000,
            "next_action": "Controlla stato gateway",
            "recent_runs": [
                {
                    "ts": now_ms - 10000,
                    "action": "finished",
                    "status": "ok",
                    "summary": "gateway ok",
                    "durationMs": 2100,
                }
            ],
        }
    ])

    assert items
    assert any(row.get("kind") == "next_run" for row in items)
    assert any(row.get("status") == "ok" for row in items)


def test_extract_document_anchors_collects_structured_lines():
    text = """
# Missione
- Devi monitorare il gateway
1. Priorità sicurezza
Nota: questo testo deve restare coerente
"""
    anchors = dashboard_app.extract_document_anchors(text, max_items=10)
    assert anchors
    assert any("Missione" in x for x in anchors)
    assert any("monitorare il gateway" in x for x in anchors)


def test_build_causal_graph_returns_nodes_and_edges():
    snapshot = {
        "agent": "Europa",
        "status": "Active",
    }
    decisions = [
        {
            "decision": "Controllare lo stato gateway",
            "source": "realtime",
            "root_causes": [{"file": "/tmp/SOUL.md", "anchors": ["Priorità sicurezza"]}],
        }
    ]
    cron_timeline = [
        {
            "kind": "finished",
            "status": "ok",
            "summary": "gateway attivo",
            "job": "Gateway watchdog",
            "ts": "2026-02-12 12:00:00",
        }
    ]
    context_roots = [
        {
            "file": "/tmp/SOUL.md",
            "matched_anchors": ["Priorità sicurezza"],
        }
    ]

    graph = dashboard_app.build_causal_graph(snapshot, decisions, cron_timeline, context_roots)
    assert "nodes" in graph and "edges" in graph
    assert len(graph["nodes"]) > 0
    assert len(graph["edges"]) > 0


def test_drilldown_includes_causal_graph_layer():
    client = dashboard_app.app.test_client()
    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
        dashboard_app.agent_state["Mercurio"] = {
            "agent": "Mercurio",
            "status": "Active",
            "task": "Analisi",
            "last_seen": "2026-02-12T12:00:00Z",
            "cron_jobs": 1,
            "message_history": [],
            "thought_history": [],
            "cron_details": [],
            "recent_messages": ["assistant: update"],
            "recent_thoughts": [],
        }

    response = client.get("/drilldown/Mercurio")
    assert response.status_code == 200
    payload = response.get_json()
    assert "causal_graph" in payload["depth"]
    assert "nodes" in payload["depth"]["causal_graph"]


def test_discover_workspace_markdown_files_is_dynamic():
    with tempfile.TemporaryDirectory() as td:
        p1 = os.path.join(td, "SOUL.md")
        p2 = os.path.join(td, "custom-guidelines.md")
        with open(p1, "w", encoding="utf-8") as f:
            f.write("# Soul")
        with open(p2, "w", encoding="utf-8") as f:
            f.write("# Custom")

        files = dashboard_app.discover_workspace_markdown_files(td, max_files=20)
        assert any(x.endswith("SOUL.md") for x in files)
        assert any(x.endswith("custom-guidelines.md") for x in files)


def test_drilldown_node_endpoint_returns_node_details():
    client = dashboard_app.app.test_client()
    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
        dashboard_app.agent_state["Europa"] = {
            "agent": "Europa",
            "status": "Active",
            "task": "Analisi",
            "last_seen": "2026-02-12T12:00:00Z",
            "cron_jobs": 1,
            "message_history": [],
            "thought_history": [],
            "recent_messages": ["assistant: heartbeat ok"],
            "recent_thoughts": [],
            "cron_details": [],
        }

    first = client.get("/drilldown/Europa")
    assert first.status_code == 200
    payload = first.get_json()
    nodes = payload.get("depth", {}).get("causal_graph", {}).get("nodes", [])
    assert nodes
    node_id = nodes[0]["id"]

    second = client.get(f"/drilldown/Europa/node/{node_id}")
    assert second.status_code == 200
    node_payload = second.get_json()
    assert node_payload["found"] is True
    assert "node" in node_payload


def test_docs_manifest_and_index_endpoint_expose_docs_files():
    manifest = dashboard_app.get_docs_manifest()
    assert manifest
    assert any(item["name"] == "INDEX.md" for item in manifest)

    client = dashboard_app.app.test_client()
    response = client.get("/docs/index")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["count"] >= 1
    assert any(item["name"] == "INDEX.md" for item in payload["docs"])


def test_docs_content_endpoint_returns_markdown_and_handles_missing_doc():
    client = dashboard_app.app.test_client()

    ok_response = client.get("/docs/content/INDEX.md")
    assert ok_response.status_code == 200
    ok_payload = ok_response.get_json()
    assert ok_payload["found"] is True
    assert ok_payload["doc"] == "INDEX.md"
    assert isinstance(ok_payload["content"], str)
    assert len(ok_payload["content"]) > 0

    missing_response = client.get("/docs/content/not-found.md")
    assert missing_response.status_code == 404
    missing_payload = missing_response.get_json()
    assert missing_payload["found"] is False
    assert missing_payload["error"] == "doc_not_found"


def test_parse_and_format_helpers_cover_time_and_message_cases():
    assert dashboard_app.parse_any_ts(123.0) == 123.0
    assert dashboard_app.parse_any_ts("2026-02-12T12:00:00Z") > 0
    assert dashboard_app.parse_any_ts("not-a-ts") == 0.0

    assert dashboard_app.fmt_seconds(42) == "42s"
    assert dashboard_app.fmt_seconds(120) == "2m"
    assert dashboard_app.fmt_seconds(7200) == "2h"

    assert dashboard_app.fmt_ts_ms(0) == ""
    assert dashboard_app.fmt_ts_ms(1710000000000)

    assert dashboard_app.parse_message_actor("user: hi") == ("user", "hi")
    assert dashboard_app.parse_message_actor("assistant: answer") == ("assistant", "answer")
    assert dashboard_app.parse_message_actor("toolresult: ok") == ("tool", "ok")
    assert dashboard_app.parse_message_actor("plain") == ("system", "plain")


def test_token_and_anchor_matching_helpers():
    anchors = ["Monitor gateway security", "Keep heartbeat active", "Other"]
    matches = dashboard_app.best_anchor_matches(anchors, "gateway security must stay active", max_items=2)
    assert matches
    assert "Monitor gateway security" in matches

    assert dashboard_app.tokenize_text(None) == set()
    assert "gateway" in dashboard_app.tokenize_text("Gateway health check")


def test_find_agent_snapshot_and_name_normalization():
    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
        dashboard_app.agent_state["Europa"] = {"agent": "Europa", "status": "Active"}

    assert dashboard_app.normalize_agent_name(" Europa ") == "europa"
    found = dashboard_app.find_agent_snapshot("europa")
    assert found is not None
    assert found["agent"] == "Europa"


def test_build_cron_details_updates_global_summary(monkeypatch):
    now_ms = int(time.time() * 1000)

    def fake_runs(_job_id, max_items=8):
        return [{"ts": now_ms - 2000, "action": "finished", "status": "ok", "summary": "done", "durationMs": 123}]

    monkeypatch.setattr(dashboard_app, "load_recent_cron_runs", fake_runs)
    dashboard_app.build_cron_details(
        {
            "cron": {
                "jobs": [
                    {
                        "id": "job-1",
                        "agentId": "europa",
                        "name": "Heartbeat",
                        "enabled": True,
                        "schedule": {"kind": "interval", "everyMs": 60000},
                        "state": {"nextRunAtMs": now_ms + 4000, "lastRunAtMs": now_ms - 2000, "lastStatus": "ok", "lastDurationMs": 123},
                        "payload": {"text": "check heartbeat"},
                    }
                ]
            }
        }
    )

    assert "Europa" in dashboard_app.cron_details_by_agent
    rows = dashboard_app.cron_details_by_agent["Europa"]
    assert rows and rows[0]["name"] == "Heartbeat"
    assert dashboard_app.cron_summary["active_jobs"] >= 1


def test_push_interaction_detects_user_and_agent_mentions():
    dashboard_app.recent_user_agent.clear()
    dashboard_app.recent_agent_agent.clear()

    dashboard_app.push_interaction(
        {
            "agent": "Europa",
            "last_seen": "2026-02-12T12:00:00Z",
            "recent_messages": ["user: check roma status", "assistant: ping Mercurio now"],
        }
    )

    assert len(dashboard_app.recent_user_agent) >= 1
    assert any(row.get("target") == "Mercurio" for row in dashboard_app.recent_agent_agent)


def test_index_docs_and_drilldown_error_paths(monkeypatch, tmp_path):
    client = dashboard_app.app.test_client()
    assert client.get("/").status_code == 200

    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
    missing_agent_node = client.get("/drilldown/ghost/node/n1")
    assert missing_agent_node.status_code == 404

    old_docs_dir = dashboard_app.DOCS_DIR
    try:
        dashboard_app.DOCS_DIR = str(tmp_path / "missing-docs")
        assert dashboard_app.get_docs_manifest() == []

        docs_dir = tmp_path / "docs"
        docs_dir.mkdir()
        (docs_dir / "INDEX.md").write_text("# Index\n", encoding="utf-8")
        (docs_dir / "notes.txt").write_text("skip", encoding="utf-8")
        (docs_dir / "fake.md").mkdir()
        dashboard_app.DOCS_DIR = str(docs_dir)
        manifest = dashboard_app.get_docs_manifest()
        assert any(item["name"] == "INDEX.md" for item in manifest)
        assert all(item["name"].endswith(".md") for item in manifest)

        monkeypatch.setattr(dashboard_app.os, "listdir", lambda _p: (_ for _ in ()).throw(RuntimeError("boom")))
        assert dashboard_app.get_docs_manifest() == []
    finally:
        dashboard_app.DOCS_DIR = old_docs_dir

    missing_blank = client.get("/docs/content/%20")
    assert missing_blank.status_code == 404

    monkeypatch.setattr(
        dashboard_app,
        "get_docs_manifest",
        lambda: [{"name": "BROKEN.md", "path": "/tmp/BROKEN.md", "is_index": False}],
    )
    original_open = builtins.open

    def fake_open(path, *args, **kwargs):
        if str(path) == "/tmp/BROKEN.md":
            raise OSError("cannot read")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fake_open)
    broken = client.get("/docs/content/BROKEN.md")
    assert broken.status_code == 500

    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
    not_found = client.get("/drilldown/ghost")
    assert not_found.status_code == 404

    with dashboard_app.state_lock:
        dashboard_app.agent_state["Europa"] = {"agent": "Europa", "status": "Active"}
    missing_node = client.get("/drilldown/Europa/node/none")
    assert missing_node.status_code == 404

    def fake_depth(_snapshot, _target):
        return {
            "causal_graph": {
                "nodes": [{"id": "n1", "label": "Node", "meta": {"file": "/tmp/SOUL.md"}}],
                "edges": [{"source": "n0", "target": "n1", "label": "in"}],
            },
            "context_roots": [{"file": "/tmp/SOUL.md", "matched_anchors": ["Mission"], "sample": "# SOUL"}],
        }

    monkeypatch.setattr(dashboard_app, "compute_drilldown_depth", fake_depth)
    node_ok = client.get("/drilldown/Europa/node/n1")
    assert node_ok.status_code == 200
    assert node_ok.get_json()["file_detail"]["file"] == "/tmp/SOUL.md"


def test_helper_fallbacks_and_name_resolution_branches(monkeypatch, tmp_path):
    real_isdir = os.path.isdir
    assert dashboard_app.should_skip_event("bad") is True

    with dashboard_app.state_lock:
        dashboard_app.agent_state.clear()
    assert dashboard_app.find_agent_snapshot("none") is None

    monkeypatch.setattr(dashboard_app, "run_openclaw_json", lambda _args: {"bad": True})
    assert dashboard_app.get_agent_registry() == []

    assert dashboard_app.read_text_file_head("/path/does/not/exist") == ""
    assert dashboard_app.extract_document_anchors(None) == []
    assert dashboard_app.parse_any_ts(None) == 0.0
    assert dashboard_app.parse_any_ts("   ") == 0.0
    assert dashboard_app.parse_message_actor(123) == ("unknown", "")
    assert dashboard_app.detect_agent_mentions(None, "Europa") == []
    assert dashboard_app.clip_text("x" * 200, max_len=12).endswith("…")

    dashboard_app.recent_user_agent.clear()
    dashboard_app.push_interaction({"agent": "Europa", "recent_messages": "bad"})
    assert len(dashboard_app.recent_user_agent) == 0

    assert dashboard_app.resolve_agent_workspace({"raw_core": {"workspace": "/tmp/work"}, "agent": "Europa"}) == "/tmp/work"

    monkeypatch.setattr(dashboard_app, "get_agent_registry", lambda: [123, {"id": "x", "name": "y"}])
    expected = os.path.expanduser("~/.openclaw/workspace-Test")
    snapshot = {"agent": "Test"}

    def fake_isdir(path):
        return path == expected

    monkeypatch.setattr(dashboard_app.os.path, "isdir", fake_isdir)
    assert dashboard_app.resolve_agent_workspace(snapshot) == expected

    monkeypatch.setattr(dashboard_app.os.path, "isdir", lambda _p: False)
    assert dashboard_app.resolve_agent_workspace(snapshot) == ""

    monkeypatch.setattr(dashboard_app.os.path, "isdir", real_isdir)

    assert dashboard_app.discover_workspace_markdown_files("/missing/path") == []

    deep_root = tmp_path / "a" / "b" / "c" / "d" / "e"
    deep_root.mkdir(parents=True)
    shallow = tmp_path / "root.md"
    broken = tmp_path / "broken.md"
    huge = tmp_path / "huge.md"
    zero = tmp_path / "zero.md"
    deep_file = deep_root / "skip.md"
    shallow.write_text("# ok", encoding="utf-8")
    broken.write_text("# broken", encoding="utf-8")
    huge.write_text("# huge", encoding="utf-8")
    zero.write_text("", encoding="utf-8")
    deep_file.write_text("# deep", encoding="utf-8")

    original_getsize = dashboard_app.os.path.getsize

    def fake_getsize(path):
        path = str(path)
        if path.endswith("broken.md"):
            raise OSError("size error")
        if path.endswith("huge.md"):
            return 700000
        return original_getsize(path)

    monkeypatch.setattr(dashboard_app.os.path, "getsize", fake_getsize)
    discovered = dashboard_app.discover_workspace_markdown_files(str(tmp_path), max_files=20)
    assert any(str(p).endswith("root.md") for p in discovered)
    assert all(not str(p).endswith("deep/skip.md") for p in discovered)

    monkeypatch.setattr(dashboard_app, "resolve_agent_workspace", lambda _snapshot: "")
    assert dashboard_app.load_agent_context_roots({"agent": "Europa"}) == []

    monkeypatch.setattr(dashboard_app, "resolve_agent_workspace", lambda _snapshot: str(tmp_path))
    monkeypatch.setattr(dashboard_app, "discover_workspace_markdown_files", lambda _w, max_files=70: [str(shallow)])
    monkeypatch.setattr(dashboard_app, "read_text_file_head", lambda _p: "")
    assert dashboard_app.load_agent_context_roots({"agent": "Europa"}) == []


def test_timeline_decision_graph_and_cron_parsers_cover_uncovered_branches(monkeypatch, tmp_path):
    dashboard_app.recent_user_agent.clear()
    dashboard_app.recent_user_agent.extend([
        "bad",
        {"agent": "Roma", "actor": "user", "text": "ignore", "ts": "2026-02-12T12:00:00Z"},
        {"agent": "Europa", "actor": "user", "text": "keep", "ts": "2026-02-12T12:00:01Z"},
    ])

    snapshot = {
        "agent": "Europa",
        "last_seen": "2026-02-12T12:00:00Z",
        "message_history": ["bad", {"ts": "2026-02-12T11:59:00Z", "text": "assistant: ok"}],
        "thought_history": ["bad", {"ts": "2026-02-12T11:59:01Z", "text": "think"}],
        "recent_messages": ["assistant: done"],
        "recent_thoughts": ["focus"],
        "cron_details": [
            "bad",
            {"name": "Job", "summary": "sum", "recent_runs": ["bad", {"action": "finished", "status": "ok", "summary": "ok", "ts": 1700000000000}]},
        ],
    }
    timeline = dashboard_app.build_agent_timeline(snapshot)
    assert timeline

    cron_timeline = dashboard_app.build_cron_timeline([
        "bad",
        {"name": "Job", "recent_runs": ["bad", {"ts": "bad"}]},
    ])
    assert cron_timeline == []

    many_rows = [{"type": "message", "text": f"decision {idx}", "source": "session", "ts": "2026-02-12T12:00:00Z"} for idx in range(40)]
    many_rows.insert(0, "bad")
    many_rows.insert(1, {"type": "message", "text": "", "source": "session", "ts": "2026-02-12T12:00:00Z"})
    decisions = dashboard_app.infer_decision_trace(
        "europa",
        many_rows,
        context_roots=["bad", {"file": "/tmp/SOUL.md", "anchors": ["decision"]}],
    )
    assert len(decisions) == 25
    assert any("Constraints/goals" in " ".join(item.get("why", [])) for item in decisions)

    graph = dashboard_app.build_causal_graph(
        {"agent": "Europa", "status": "Active"},
        [],
        [
            {"kind": "ignored", "summary": "skip", "status": "ok", "job": "J"},
            {"kind": "finished", "summary": "run", "status": "failed", "job": "J", "ts": "2026-02-12 12:00:00"},
        ],
        [],
    )
    assert any(edge["label"] == "acts" for edge in graph["edges"])
    assert any(node["group"] == "outcome_bad" for node in graph["nodes"])

    assert dashboard_app.decode_json_stream(None) == []
    decoded = dashboard_app.decode_json_stream('{"a":1} junk {"b":2}')
    assert decoded and decoded[0]["a"] == 1 and decoded[1]["b"] == 2
    assert dashboard_app.decode_json_stream('{"a":1}   ')[0]["a"] == 1

    extra_decisions = dashboard_app.infer_decision_trace(
        "europa",
        [{"type": "message", "text": "choose", "source": "session", "ts": "2026-02-12T12:00:00Z"}],
        context_roots=["bad"],
    )
    assert extra_decisions

    decisions_with_empty_prev = dashboard_app.infer_decision_trace(
        "europa",
        [
            {"type": "message", "text": "decide", "source": "session", "ts": "2026-02-12T12:00:00Z"},
            {"type": "thought", "text": "", "source": "session", "ts": "2026-02-12T11:59:59Z"},
        ],
    )
    assert decisions_with_empty_prev

    old_runs_dir = dashboard_app.CRON_RUNS_DIR
    dashboard_app.CRON_RUNS_DIR = str(tmp_path)
    assert dashboard_app.load_recent_cron_runs("missing") == []

    ok_path = tmp_path / "ok.jsonl"
    ok_path.write_text('{"x":1}\n42\n{"y":2}\n', encoding="utf-8")
    ok_rows = dashboard_app.load_recent_cron_runs("ok")
    assert len(ok_rows) == 2
    assert ok_rows[0]["x"] == 1 and ok_rows[1]["y"] == 2

    broken_path = tmp_path / "broken.jsonl"
    broken_path.write_text('{"x":1}\n', encoding="utf-8")
    original_open = builtins.open

    def fail_open(path, *args, **kwargs):
        if str(path).endswith("broken.jsonl"):
            raise OSError("boom")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", fail_open)
    assert dashboard_app.load_recent_cron_runs("broken") == []
    dashboard_app.CRON_RUNS_DIR = old_runs_dir


def test_builders_and_snapshot_merge_cover_remaining_core_branches(monkeypatch):
    now_ms = int(time.time() * 1000)

    dashboard_app.build_cron_details(
        {
            "cron": {
                "jobs": [
                    "bad",
                    {"id": "x"},
                    {
                        "id": "job-err",
                        "agentId": "europa",
                        "name": "ErrJob",
                        "enabled": True,
                        "state": {"lastStatus": "failed", "nextRunAtMs": now_ms + 5000},
                        "payload": {"text": "do something"},
                    },
                ]
            }
        }
    )
    assert dashboard_app.cron_summary["last_errors"]

    dashboard_app.compute_core_capabilities({"agents": [], "cron": {"jobs": []}, "status": {}, "presence": {}})
    assert dashboard_app.CORE_CAPABILITIES["channels"]["agents_list"] is True
    assert dashboard_app.CORE_CAPABILITIES["channels"]["cron_list"] is True
    assert dashboard_app.CORE_CAPABILITIES["channels"]["status"] is True
    assert dashboard_app.CORE_CAPABILITIES["channels"]["presence"] is True

    dashboard_app.cron_details_by_agent = {
        "Europa": [{"interrupted": True, "name": "ErrJob"}]
    }
    states = dashboard_app.build_core_agent_states(
        {
            "agents": ["bad", {}, {"id": "europa", "name": "Europa"}],
            "cron": {
                "jobs": [
                    "bad",
                    {},
                    {
                        "agentId": "europa",
                        "name": "Heartbeat",
                        "enabled": True,
                        "state": {"nextRunAtMs": now_ms + 1000},
                    },
                ]
            },
            "status": {
                "sessions": {
                    "recent": [
                        "bad",
                        {},
                        {"agentId": "europa", "age": 500000, "updatedAt": now_ms, "model": "gpt-5"},
                    ]
                }
            },
        }
    )
    assert states and states[0]["status"] == "Attention"
    assert states[0]["task"].endswith("non-ok")

    emitted = []
    monkeypatch.setattr(dashboard_app.socketio, "emit", lambda event, payload, room=None: emitted.append((event, payload, room)))

    old_mode = dashboard_app.OPENCLAW_MODE
    old_ready = dashboard_app.BUS_READY
    try:
        dashboard_app.OPENCLAW_MODE = "auto"
        dashboard_app.BUS_READY = False
        with dashboard_app.state_lock:
            dashboard_app.agent_state.clear()

        dashboard_app.apply_core_snapshot("bad")
        dashboard_app.apply_core_snapshot([
            {"bad": True},
            {
                "agent": "Europa",
                "status": "Active",
                "task": "Run",
                "last_seen": "2026-02-12T12:00:00Z",
                "cron_jobs": 1,
                "active_missions": ["Heartbeat"],
                "recent_messages": ["assistant: ok"],
                "raw": {"source": "core"},
            },
        ])
    finally:
        dashboard_app.OPENCLAW_MODE = old_mode
        dashboard_app.BUS_READY = old_ready

    assert any(row[0] == "init" for row in emitted)
