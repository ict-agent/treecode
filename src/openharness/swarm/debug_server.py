"""Minimal HTTP server for the swarm debugger web console."""

from __future__ import annotations

import asyncio
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

from openharness.swarm.debugger import SwarmDebuggerService


_INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>OpenHarness Swarm Debugger</title>
    <style>
      body { font-family: sans-serif; margin: 0; background: #0f172a; color: #e2e8f0; }
      header { padding: 16px 20px; border-bottom: 1px solid #334155; }
      main { display: grid; grid-template-columns: 280px 1fr 360px; min-height: calc(100vh - 65px); }
      section { padding: 16px; border-right: 1px solid #334155; overflow: auto; }
      section:last-child { border-right: 0; }
      h1, h2, h3 { margin: 0 0 12px; }
      .card { background: #111827; border: 1px solid #334155; border-radius: 8px; padding: 12px; margin-bottom: 12px; }
      .muted { color: #94a3b8; font-size: 0.9rem; }
      code { color: #93c5fd; }
      ul { padding-left: 18px; }
      button { background: #2563eb; color: white; border: 0; border-radius: 6px; padding: 8px 10px; cursor: pointer; }
      textarea { width: 100%; min-height: 72px; background: #020617; color: #e2e8f0; border: 1px solid #334155; border-radius: 6px; }
      .row { display: flex; gap: 8px; align-items: center; }
    </style>
  </head>
  <body>
    <header>
      <h1>OpenHarness Swarm Debugger</h1>
      <div class="muted">Tree, timeline, messages, approvals, playback, and control hooks.</div>
    </header>
    <main>
      <section>
        <h2>Tree</h2>
        <div class="card">
          <h3>Overview</h3>
          <div id="overview" class="muted">Waiting for snapshot...</div>
        </div>
        <div class="card">
          <h3>Scenarios</h3>
          <div class="row" style="margin-bottom:8px">
            <button onclick="runScenario('single_child')">single_child</button>
            <button onclick="runScenario('two_level_fanout')">two_level_fanout</button>
            <button onclick="runScenario('approval_on_leaf')">approval_on_leaf</button>
          </div>
        </div>
        <div class="card">
          <h3>Scenario View</h3>
          <div id="scenario-view" class="muted">Run a scenario to see grouped levels.</div>
        </div>
        <div id="tree"></div>
      </section>
      <section>
        <h2>Agent Activity</h2>
        <div class="card">
          <label class="muted" for="playback-limit">Playback event limit</label>
          <div class="row">
            <input id="playback-limit" type="number" min="1" style="flex:1">
            <button onclick="loadPlayback()">Replay</button>
            <button onclick="loadSnapshot()">Live</button>
          </div>
        </div>
        <div id="activity"></div>
        <div class="card">
          <h3>Recent Events</h3>
          <div id="timeline"></div>
        </div>
      </section>
      <section>
        <h2>Inspector</h2>
        <div id="inspector" class="card muted">Select an agent in the tree.</div>
        <div class="card">
          <h3>Inject Message</h3>
          <input id="target-agent" placeholder="agent_id" style="width:100%;margin-bottom:8px">
          <textarea id="target-message" placeholder="Message"></textarea>
          <div class="row" style="margin-top:8px">
            <button onclick="sendMessage()">Send</button>
          </div>
        </div>
        <div class="card">
          <h3>Approvals</h3>
          <div id="approvals"></div>
        </div>
        <div class="card">
          <h3>Message Graph</h3>
          <div id="message-graph"></div>
        </div>
      </section>
    </main>
    <script>
      let currentSnapshot = null;

      async function fetchJson(url, options) {
        const response = await fetch(url, options);
        return await response.json();
      }

      function renderSnapshot(snapshot) {
        currentSnapshot = snapshot;
        const overviewEl = document.getElementById('overview');
        overviewEl.innerHTML = `
          <div>Agents: <strong>${snapshot.overview.agent_count}</strong></div>
          <div>Roots: <strong>${snapshot.overview.root_count}</strong></div>
          <div>Depth: <strong>${snapshot.overview.max_depth}</strong></div>
          <div>Messages: <strong>${snapshot.overview.message_count}</strong></div>
          <div>Pending approvals: <strong>${snapshot.overview.pending_approvals}</strong></div>
          <div>Leaf agents: <strong>${snapshot.overview.leaf_agents.join(', ') || 'none'}</strong></div>
        `;

        const treeEl = document.getElementById('tree');
        treeEl.innerHTML = '';
        for (const root of snapshot.tree.roots) {
          treeEl.appendChild(renderNode(root, snapshot.tree.nodes));
        }

        const scenarioViewEl = document.getElementById('scenario-view');
        const levelMarkup = snapshot.scenario_view.levels.map(level => `
          <div class="card">
            <div><strong>Level ${level.depth}</strong></div>
            <div class="muted">${level.agents.join(', ') || 'none'}</div>
          </div>
        `).join('');
        const routeMarkup = Object.entries(snapshot.scenario_view.route_summary).map(([source, targets]) => `
          <div class="muted"><strong>${source}</strong> -> ${targets.join(', ')}</div>
        `).join('');
        scenarioViewEl.innerHTML = `
          <div class="muted">Scenario: ${snapshot.scenario_view.scenario_name || 'live runtime'}</div>
          ${levelMarkup || '<div class="muted">No grouped levels.</div>'}
          ${routeMarkup ? `<div class="card"><strong>Routes</strong>${routeMarkup}</div>` : ''}
        `;

        const activityEl = document.getElementById('activity');
        activityEl.innerHTML = Object.entries(snapshot.activity).map(([agentId, item]) => `
          <div class="card">
            <div><strong>${agentId}</strong></div>
            <div class="muted">status: ${item.status} | parent: ${item.parent_agent_id || 'root'}</div>
            <div class="muted">children: ${item.children.join(', ') || 'none'}</div>
            <div class="muted">messages: sent ${item.messages_sent}, received ${item.messages_received}</div>
            <div class="muted">recent: ${item.recent_events.join(', ') || 'none'}</div>
          </div>
        `).join('');

        const timelineEl = document.getElementById('timeline');
        timelineEl.innerHTML = snapshot.timeline.slice(-8).map(event => `
          <div class="card">
            <div><strong>${event.event_type}</strong></div>
            <div class="muted">${event.agent_id}</div>
          </div>
        `).join('');

        const approvalsEl = document.getElementById('approvals');
        approvalsEl.innerHTML = snapshot.approval_queue.map(item => `
          <div class="card">
            <div><strong>${item.tool_name || 'approval'}</strong></div>
            <div class="muted">${item.agent_id} / ${item.status}</div>
            ${item.status === 'pending' ? `
              <div class="row" style="margin-top:8px">
                <button onclick="resolveApproval('${item.correlation_id}', 'approved')">Approve</button>
                <button onclick="resolveApproval('${item.correlation_id}', 'rejected')">Reject</button>
              </div>
            ` : ''}
          </div>
        `).join('') || '<div class="muted">No approvals.</div>';

        const graphEl = document.getElementById('message-graph');
        graphEl.innerHTML = snapshot.message_graph.map(edge => `
          <div class="card">
            <div><strong>${edge.from_agent}</strong> -> <strong>${edge.to_agent}</strong></div>
            <div class="muted">${edge.event_type}</div>
            <div>${edge.text || ''}</div>
          </div>
        `).join('') || '<div class="muted">No messages.</div>';
      }

      function renderNode(agentId, nodes) {
        const node = nodes[agentId];
        const wrapper = document.createElement('div');
        wrapper.className = 'card';
        wrapper.innerHTML = `<strong>${agentId}</strong><div class="muted">${node.status}</div>`;
        wrapper.onclick = () => inspectAgent(agentId);
        for (const child of node.children) {
          const childNode = renderNode(child, nodes);
          childNode.style.marginLeft = '12px';
          wrapper.appendChild(childNode);
        }
        return wrapper;
      }

      async function inspectAgent(agentId) {
        const payload = await fetchJson(`/api/agents/${encodeURIComponent(agentId)}`);
        document.getElementById('inspector').innerHTML = `
          <div><strong>${payload.agent_id}</strong></div>
          <div class="muted">session: ${payload.context?.session_id || 'n/a'}</div>
          <div style="margin-top:8px"><code>${payload.context?.prompt || ''}</code></div>
          <div class="muted" style="margin-top:8px">Messages: ${(payload.context?.messages || []).join(' | ')}</div>
        `;
        document.getElementById('target-agent').value = agentId;
      }

      async function sendMessage() {
        const agentId = document.getElementById('target-agent').value;
        const message = document.getElementById('target-message').value;
        await fetchJson(`/api/agents/${encodeURIComponent(agentId)}/message`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({message}),
        });
        await loadSnapshot();
      }

      async function loadSnapshot() {
        renderSnapshot(await fetchJson('/api/snapshot'));
      }

      async function runScenario(name) {
        await fetchJson(`/api/scenarios/${encodeURIComponent(name)}/run`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: '{}',
        });
        await loadSnapshot();
      }

      async function resolveApproval(correlationId, status) {
        await fetchJson(`/api/approvals/${encodeURIComponent(correlationId)}/resolve`, {
          method: 'POST',
          headers: {'Content-Type': 'application/json'},
          body: JSON.stringify({status}),
        });
        await loadSnapshot();
      }

      async function loadPlayback() {
        const limit = document.getElementById('playback-limit').value;
        const url = limit ? `/api/playback?limit=${encodeURIComponent(limit)}` : '/api/playback';
        renderSnapshot(await fetchJson(url));
      }

      loadSnapshot();
      setInterval(loadSnapshot, 2000);
    </script>
  </body>
</html>
"""


class SwarmDebugServer:
    """Serve debugger snapshots and control endpoints over HTTP."""

    def __init__(self, *, service: SwarmDebuggerService, host: str = "127.0.0.1", port: int = 0) -> None:
        self._service = service
        self._host = host
        self._port = port
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def base_url(self) -> str:
        """Return the base URL once the server is started."""
        assert self._server is not None
        host, port = self._server.server_address
        return f"http://{host}:{port}"

    def start(self) -> None:
        """Start the HTTP server in a background thread."""
        service = self._service

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                if parsed.path == "/":
                    self._respond(HTTPStatus.OK, _INDEX_HTML, content_type="text/html; charset=utf-8")
                    return
                if parsed.path == "/api/snapshot":
                    self._respond_json(service.snapshot())
                    return
                if parsed.path == "/api/overview":
                    self._respond_json(service.snapshot()["overview"])
                    return
                if parsed.path == "/api/scenario-view":
                    self._respond_json(service.snapshot()["scenario_view"])
                    return
                if parsed.path == "/api/scenarios":
                    self._respond_json({"scenarios": list(service.list_scenarios())})
                    return
                if parsed.path == "/api/tree":
                    self._respond_json(service.snapshot()["tree"])
                    return
                if parsed.path == "/api/timeline":
                    self._respond_json(service.snapshot()["timeline"])
                    return
                if parsed.path == "/api/message-graph":
                    self._respond_json(service.snapshot()["message_graph"])
                    return
                if parsed.path == "/api/approval-queue":
                    self._respond_json(service.snapshot()["approval_queue"])
                    return
                if parsed.path == "/api/playback":
                    params = parse_qs(parsed.query)
                    limit = params.get("limit", [None])[0]
                    try:
                        event_limit = int(limit) if limit else None
                    except ValueError:
                        self.send_error(HTTPStatus.BAD_REQUEST, "limit must be an integer")
                        return
                    payload = service.playback(event_limit=event_limit)
                    self._respond_json(payload)
                    return
                if parsed.path.startswith("/api/agents/"):
                    agent_id = unquote(parsed.path[len("/api/agents/"):])
                    if "/" in agent_id:
                        agent_id = agent_id.split("/", 1)[0]
                    snapshot = service.snapshot()
                    self._respond_json(
                        {
                            "agent_id": agent_id,
                            "context": snapshot["contexts"].get(agent_id),
                            "node": snapshot["tree"]["nodes"].get(agent_id),
                        }
                    )
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def do_POST(self) -> None:  # noqa: N802
                parsed = urlparse(self.path)
                payload = self._read_json()
                if parsed.path.startswith("/api/agents/") and parsed.path.endswith("/message"):
                    agent_id = unquote(parsed.path[len("/api/agents/"):-len("/message")])
                    result = asyncio.run(service.send_message(agent_id, str(payload.get("message", ""))))
                    self._respond_json(result)
                    return
                if parsed.path.startswith("/api/scenarios/") and parsed.path.endswith("/run"):
                    scenario_name = unquote(parsed.path[len("/api/scenarios/"):-len("/run")])
                    try:
                        result = service.run_scenario(scenario_name)
                    except ValueError as exc:
                        self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                        return
                    self._respond_json(result)
                    return
                if parsed.path.startswith("/api/agents/") and parsed.path.endswith("/pause"):
                    agent_id = unquote(parsed.path[len("/api/agents/"):-len("/pause")])
                    result = asyncio.run(service.pause_agent(agent_id))
                    self._respond_json({"ok": result})
                    return
                if parsed.path.startswith("/api/agents/") and parsed.path.endswith("/resume"):
                    agent_id = unquote(parsed.path[len("/api/agents/"):-len("/resume")])
                    result = asyncio.run(service.resume_agent(agent_id))
                    self._respond_json({"ok": result})
                    return
                if parsed.path.startswith("/api/agents/") and parsed.path.endswith("/stop"):
                    agent_id = unquote(parsed.path[len("/api/agents/"):-len("/stop")])
                    result = asyncio.run(service.stop_agent(agent_id))
                    self._respond_json({"ok": result})
                    return
                if parsed.path.startswith("/api/agents/") and parsed.path.endswith("/context-patch"):
                    agent_id = unquote(parsed.path[len("/api/agents/"):-len("/context-patch")])
                    snapshot = service.apply_context_patch(
                        agent_id,
                        patch=dict(payload.get("patch", {})),
                        base_version=int(payload.get("base_version", 1)),
                    )
                    self._respond_json(snapshot.to_dict())
                    return
                if parsed.path.startswith("/api/approvals/") and parsed.path.endswith("/resolve"):
                    correlation_id = unquote(parsed.path[len("/api/approvals/"):-len("/resolve")])
                    try:
                        result = asyncio.run(
                            service.resolve_approval(
                                correlation_id,
                                status=str(payload.get("status", "approved")),
                            )
                        )
                    except ValueError as exc:
                        self.send_error(HTTPStatus.BAD_REQUEST, str(exc))
                        return
                    self._respond_json(result)
                    return
                self.send_error(HTTPStatus.NOT_FOUND)

            def log_message(self, format: str, *args) -> None:  # noqa: A003
                del format, args

            def _read_json(self) -> dict[str, object]:
                length = int(self.headers.get("Content-Length", "0"))
                raw = self.rfile.read(length) if length else b"{}"
                return json.loads(raw.decode("utf-8"))

            def _respond_json(self, payload: object) -> None:
                self._respond(HTTPStatus.OK, json.dumps(payload), content_type="application/json")

            def _respond(self, status: HTTPStatus, payload: str, *, content_type: str) -> None:
                data = payload.encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._server = ThreadingHTTPServer((self._host, self._port), Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """Stop the HTTP server and wait for the thread to finish."""
        if self._server is not None:
            self._server.shutdown()
            self._server.server_close()
        if self._thread is not None:
            self._thread.join(timeout=5)
