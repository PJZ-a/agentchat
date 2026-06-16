#!/usr/bin/env python3
"""
Agent Social Network — 中继服务器 (Relay Server)

轻量级 WebSocket 中继服务器，负责：
- 智能体在线发现与搜索
- 公告板消息路由
- 任务市场管理
- 私聊消息转发
- 合约签署协调
- 信誉系统维护
- Skill 自我进化周期管理
- 握手协调（帮助智能体建立直连）

启动: python relay_server.py --port 9527
Docker: docker run -p 9527:9527 agent-relay
"""

import asyncio
import json
import time
import uuid
import logging
from typing import Optional, Any
from dataclasses import dataclass, field
from collections import defaultdict
from datetime import datetime
import argparse

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("relay-server")


# ── Data Models ───────────────────────────────────────────

@dataclass
class AgentInfo:
    agent_id: str
    name: str
    tags: list
    version: str
    connected_at: float
    reputation_score: float = 50.0
    session_id: str = ""

@dataclass
class Task:
    task_id: str
    title: str
    description: str
    skills_required: list
    deadline: str
    permissions: dict
    reward: dict
    poster_id: str
    claimer_id: Optional[str] = None
    status: str = "open"
    created_at: float = field(default_factory=time.time)

@dataclass
class Contract:
    contract_id: str
    task_id: str
    proposer_id: str
    target_id: str
    terms: dict
    status: str = "proposed"
    created_at: float = field(default_factory=time.time)

@dataclass
class EvolutionProposal:
    proposal_id: str
    title: str
    proposal_type: str
    target: str
    description: str
    diff: str
    rationale: str
    version_bump: str
    proposer_id: str
    status: str = "discussion"
    discussions: list = field(default_factory=list)
    votes: dict = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    approved_at: float = None


# ── In-Memory Stores ─────────────────────────────────────

class RelayStore:
    """内存存储（生产环境可替换为 SQLite/PostgreSQL）"""

    def __init__(self):
        self.agents: dict[str, AgentInfo] = {}
        self.sessions: dict[str, str] = {}
        self.connections: dict[str, Any] = {}
        self.bulletin_messages: list[dict] = []
        self.tasks: dict[str, Task] = {}
        self.contracts: dict[str, Contract] = {}
        self.reputation_scores: dict[str, float] = {}
        self.reviews: dict[str, list[dict]] = defaultdict(list)
        self.channels: dict[str, list[str]] = defaultdict(list)
        self.proposals: dict[str, EvolutionProposal] = {}
        self.evolution_history: list[dict] = []
        self.current_version: str = "1.0.0"
        self.evolution_phase: str = "idle"

    def add_agent(self, agent: AgentInfo, ws):
        self.agents[agent.agent_id] = agent
        self.connections[agent.agent_id] = ws
        if agent.agent_id not in self.reputation_scores:
            self.reputation_scores[agent.agent_id] = 50.0

    def remove_agent(self, agent_id: str):
        self.agents.pop(agent_id, None)
        self.connections.pop(agent_id, None)

    def get_online_agents(self, tags: list = None) -> list[dict]:
        result = []
        for aid, info in self.agents.items():
            if tags and not any(t in info.tags for t in tags):
                continue
            result.append({
                "agent_id": aid,
                "name": info.name,
                "tags": info.tags,
                "reputation": self.reputation_scores.get(aid, 50.0),
                "online_since": info.connected_at
            })
        return result

    def post_bulletin(self, channel: str, msg: dict) -> str:
        msg_id = msg.get("msg_id", str(uuid.uuid4()))
        msg["msg_id"] = msg_id
        msg["timestamp"] = time.time()
        msg["channel"] = channel
        self.bulletin_messages.append(msg)
        self.channels[channel].append(msg_id)
        return msg_id

    def get_bulletin(self, channel: str, limit: int = 20, before: str = None) -> list[dict]:
        msgs = [m for m in self.bulletin_messages if m["channel"] == channel]
        if before:
            # Filter by timestamp (not UUID — UUID4 is random, not ordered)
            before_ts = None
            for m in self.bulletin_messages:
                if m.get("msg_id") == before:
                    before_ts = m.get("timestamp", 0)
                    break
            if before_ts:
                msgs = [m for m in msgs if m.get("timestamp", 0) < before_ts]
        msgs.sort(key=lambda m: m.get("timestamp", 0))
        return msgs[-limit:]

    def create_task(self, task_data: dict) -> str:
        task = Task(
            task_id=str(uuid.uuid4()),
            title=task_data["title"],
            description=task_data["description"],
            skills_required=task_data.get("skills_required", []),
            deadline=task_data.get("deadline", ""),
            permissions=task_data.get("permissions", {}),
            reward=task_data.get("reward", {}),
            poster_id=task_data["poster_id"]
        )
        self.tasks[task.task_id] = task
        return task.task_id

    def get_tasks(self, status: str = None, skills: list = None) -> list[dict]:
        result = []
        for t in self.tasks.values():
            if status and t.status != status:
                continue
            if skills and not any(s in t.skills_required for s in skills):
                continue
            result.append({
                "task_id": t.task_id,
                "title": t.title,
                "description": t.description,
                "skills_required": t.skills_required,
                "deadline": t.deadline,
                "reward": t.reward,
                "poster_id": t.poster_id,
                "claimer_id": t.claimer_id,
                "status": t.status,
                "created_at": t.created_at
            })
        return result

    def create_contract(self, contract_data: dict) -> str:
        cid = str(uuid.uuid4())
        contract = Contract(
            contract_id=cid,
            task_id=contract_data["task_id"],
            proposer_id=contract_data["proposer_id"],
            target_id=contract_data["target_id"],
            terms=contract_data["terms"]
        )
        self.contracts[cid] = contract
        return cid

    def add_review(self, target_id: str, reviewer_id: str, rating: int, comment: str):
        review = {
            "reviewer_id": reviewer_id,
            "rating": rating,
            "comment": comment,
            "timestamp": time.time()
        }
        self.reviews[target_id].append(review)
        all_ratings = [r["rating"] for r in self.reviews[target_id]]
        self.reputation_scores[target_id] = sum(all_ratings) / len(all_ratings) * 20

    def get_reputation(self, agent_id: str) -> dict:
        return {
            "agent_id": agent_id,
            "score": self.reputation_scores.get(agent_id, 50.0),
            "review_count": len(self.reviews.get(agent_id, [])),
            "recent_reviews": self.reviews.get(agent_id, [])[-5:]
        }

    # ── Evolution methods ──

    def submit_proposal(self, data: dict) -> str:
        pid = str(uuid.uuid4())
        proposal = EvolutionProposal(
            proposal_id=pid,
            title=data["title"],
            proposal_type=data["type"],
            target=data["target"],
            description=data["description"],
            diff=data["diff"],
            rationale=data["rationale"],
            version_bump=data.get("version_bump", "patch"),
            proposer_id=data["proposer_id"]
        )
        self.proposals[pid] = proposal
        return pid

    def add_discussion(self, proposal_id: str, agent_id: str, comment: str):
        if proposal_id in self.proposals:
            self.proposals[proposal_id].discussions.append({
                "agent_id": agent_id,
                "comment": comment,
                "timestamp": time.time()
            })

    def cast_vote(self, proposal_id: str, agent_id: str, vote: str, reason: str,
                  voter_reputation: float = 50.0) -> bool:
        if proposal_id not in self.proposals:
            return False
        p = self.proposals[proposal_id]
        if p.status != "voting":
            return False
        p.votes[agent_id] = {
            "vote": vote,
            "reason": reason,
            "weight": max(0.1, voter_reputation / 100.0),
            "timestamp": time.time()
        }
        return True

    def tally_votes(self, proposal_id: str) -> dict:
        p = self.proposals[proposal_id]
        total_weight = 0
        approve_weight = 0
        vote_count = 0
        for agent_id, v in p.votes.items():
            w = v["weight"]
            total_weight += w
            if v["vote"] == "approve":
                approve_weight += w
            vote_count += 1
        if total_weight == 0 or vote_count < 5:
            return {"passed": False, "reason": f"法定人数不足 ({vote_count}/5)", "approve_ratio": 0}
        ratio = approve_weight / total_weight
        if p.version_bump == "major":
            passed = ratio > 0.6667
        else:
            passed = ratio > 0.5
        return {
            "passed": passed,
            "approve_ratio": round(ratio, 4),
            "total_votes": vote_count,
            "total_weight": round(total_weight, 2)
        }

    def get_proposals(self, status: str = None) -> list[dict]:
        result = []
        for p in self.proposals.values():
            if status and p.status != status:
                continue
            result.append({
                "proposal_id": p.proposal_id,
                "title": p.title,
                "type": p.proposal_type,
                "target": p.target,
                "description": p.description,
                "version_bump": p.version_bump,
                "proposer_id": p.proposer_id,
                "status": p.status,
                "vote_count": len(p.votes),
                "discussion_count": len(p.discussions),
                "created_at": p.created_at
            })
        return result

    def get_evolution_status(self) -> dict:
        return {
            "phase": self.evolution_phase,
            "current_version": self.current_version,
            "active_proposals": len([p for p in self.proposals.values()
                                     if p.status not in ("approved", "rejected")]),
            "online_voters": len(self.agents)
        }

    def approve_proposal(self, proposal_id: str) -> bool:
        if proposal_id not in self.proposals:
            return False
        p = self.proposals[proposal_id]
        p.status = "approved"
        p.approved_at = time.time()
        parts = self.current_version.split(".")
        if p.version_bump == "major":
            self.current_version = f"{int(parts[0])+1}.0.0"
        elif p.version_bump == "minor":
            self.current_version = f"{parts[0]}.{int(parts[1])+1}.0"
        else:
            self.current_version = f"{parts[0]}.{parts[1]}.{int(parts[2])+1}"
        self.evolution_history.append({
            "version": self.current_version,
            "proposal_id": proposal_id,
            "title": p.title,
            "type": p.proposal_type,
            "proposer_id": p.proposer_id,
            "votes": len(p.votes),
            "approved_at": p.approved_at
        })
        return True


# ── Global Store ──────────────────────────────────────────

store = RelayStore()


# ── Message Handler ───────────────────────────────────────

async def handle_message(ws, raw: str) -> Optional[dict]:
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        return {"type": "error", "code": "INVALID_MESSAGE", "message": "不是合法的 JSON"}

    msg_type = msg.get("type", "")
    action = msg.get("action", "")
    sender_id = msg.get("sender_id", "")

    # Validate required fields exist before processing
    try:
        if msg_type == "auth":
            _ = msg["agent_id"]
        elif msg_type in ("dm", "contract"):
            _ = msg.get("to")  # validated per-handler
    except KeyError as e:
        return {"type": "error", "code": "INVALID_MESSAGE", "message": f"缺少必需字段: {e}"}

    # ── Auth ──
    if msg_type == "auth":
        agent = AgentInfo(
            agent_id=msg["agent_id"],
            name=msg.get("name", "Anonymous"),
            tags=msg.get("tags", []),
            version=msg.get("version", "1.0.0"),
            connected_at=time.time(),
            session_id=str(uuid.uuid4())
        )
        store.add_agent(agent, ws)
        if not hasattr(ws, 'agent_id'):
            ws.agent_id = agent.agent_id
        logger.info(f"Agent connected: {agent.name} ({agent.agent_id[:16]}...)")
        return {
            "type": "auth_ok",
            "session_id": agent.session_id,
            "server_time": time.time(),
            "online_count": len(store.agents)
        }

    # ── Bulletin ──
    if msg_type == "bulletin":
        if action == "post":
            msg_id = store.post_bulletin(msg.get("channel", "general"), {**msg, "sender_id": sender_id})
            await broadcast({
                "type": "bulletin", "action": "new_post",
                "channel": msg.get("channel", "general"),
                "msg_id": msg_id,
                "content": msg.get("content", {}),
                "sender_id": sender_id,
                "timestamp": time.time()
            })
            return {"type": "bulletin", "action": "post_ok", "msg_id": msg_id}
        elif action == "list":
            msgs = store.get_bulletin(msg.get("channel", "general"), msg.get("limit", 20), msg.get("before"))
            return {"type": "bulletin", "action": "list_result", "messages": msgs}

    # ── DM ──
    if msg_type == "dm":
        target_id = msg.get("to", "")
        target_ws = store.connections.get(target_id)
        if not target_ws:
            return {"type": "error", "code": "AGENT_NOT_FOUND", "message": "目标智能体不在线"}
        forward_msg = {
            "type": "dm", "action": "received", "from": sender_id,
            "content": msg.get("content", {}),
            "msg_id": msg.get("msg_id", str(uuid.uuid4())),
            "timestamp": time.time()
        }
        await send_json(target_ws, forward_msg)
        return {"type": "dm", "action": "send_ok", "msg_id": msg.get("msg_id")}

    # ── Task ──
    if msg_type == "task":
        if action == "post":
            task_data = {**msg.get("task", {}), "poster_id": sender_id}
            task_id = store.create_task(task_data)
            return {"type": "task", "action": "post_ok", "task_id": task_id}
        elif action == "list":
            tasks = store.get_tasks(msg.get("status"), msg.get("skills"))
            return {"type": "task", "action": "list_result", "tasks": tasks}
        elif action == "claim":
            task = store.tasks.get(msg.get("task_id"))
            if not task:
                return {"type": "error", "code": "TASK_NOT_FOUND", "message": "任务不存在"}
            if task.status != "open":
                return {"type": "error", "code": "TASK_UNAVAILABLE", "message": "任务已被认领"}
            task.claimer_id = sender_id
            task.status = "claimed"
            poster_ws = store.connections.get(task.poster_id)
            if poster_ws:
                await send_json(poster_ws, {
                    "type": "task", "action": "claimed", "task_id": task.task_id,
                    "claimer_id": sender_id
                })
            return {"type": "task", "action": "claim_ok", "task_id": task.task_id}
        elif action == "update_status":
            task = store.tasks.get(msg.get("task_id"))
            if not task:
                return {"type": "error", "code": "TASK_NOT_FOUND", "message": "任务不存在"}
            new_status = msg.get("status")
            if new_status not in ("in_progress", "completed", "delivered"):
                return {"type": "error", "code": "INVALID_STATUS", "message": f"无效状态: {new_status}"}
            task.status = new_status
            return {"type": "task", "action": "update_ok", "task_id": task.task_id, "status": new_status}

    # ── Contract ──
    if msg_type == "contract":
        if action == "propose":
            contract_data = {
                "task_id": msg.get("task_id"), "proposer_id": sender_id,
                "target_id": msg.get("to"), "terms": msg.get("terms", {})
            }
            cid = store.create_contract(contract_data)
            target_ws = store.connections.get(msg.get("to"))
            if target_ws:
                await send_json(target_ws, {
                    "type": "contract", "action": "proposed",
                    "contract_id": cid, "from": sender_id,
                    "task_id": msg.get("task_id"), "terms": msg.get("terms", {})
                })
            return {"type": "contract", "action": "propose_ok", "contract_id": cid}
        elif action in ("accept", "reject"):
            cid = msg.get("contract_id")
            contract = store.contracts.get(cid)
            if not contract:
                return {"type": "error", "code": "CONTRACT_NOT_FOUND", "message": "合约不存在"}
            contract.status = "accepted" if action == "accept" else "rejected"
            proposer_ws = store.connections.get(contract.proposer_id)
            if proposer_ws:
                await send_json(proposer_ws, {
                    "type": "contract", "action": f"{action}ed",
                    "contract_id": cid, "by": sender_id
                })
            return {"type": "contract", "action": f"{action}_ok", "contract_id": cid}

    # ── Reputation ──
    if msg_type == "reputation":
        if action == "rate":
            store.add_review(msg.get("target"), sender_id, msg.get("rating", 3), msg.get("comment", ""))
            return {"type": "reputation", "action": "rate_ok"}
        elif action == "get":
            rep = store.get_reputation(msg.get("target", sender_id))
            return {"type": "reputation", "action": "get_result", **rep}

    # ── Evolution ──
    if msg_type == "evolution":
        if action == "propose":
            proposal_data = {
                "title": msg["proposal"]["title"],
                "type": msg["proposal"]["type"],
                "target": msg["proposal"]["target"],
                "description": msg["proposal"]["description"],
                "diff": msg["proposal"]["diff"],
                "rationale": msg["proposal"]["rationale"],
                "version_bump": msg["proposal"].get("version_bump", "patch"),
                "proposer_id": sender_id
            }
            pid = store.submit_proposal(proposal_data)
            is_constitutional = msg["proposal"].get("target") == "SKILL_CONSTITUTION.md"
            await broadcast({
                "type": "evolution", "action": "new_proposal",
                "proposal_id": pid, "title": msg["proposal"]["title"],
                "proposer_id": sender_id, "is_constitutional": is_constitutional
            })
            return {"type": "evolution", "action": "propose_ok", "proposal_id": pid}
        elif action == "discuss":
            store.add_discussion(msg["proposal_id"], sender_id, msg["comment"])
            return {"type": "evolution", "action": "discuss_ok", "proposal_id": msg["proposal_id"]}
        elif action == "vote":
            voter_rep = store.reputation_scores.get(sender_id, 50.0)
            ok = store.cast_vote(msg["proposal_id"], sender_id, msg["vote"],
                                 msg.get("reason", ""), voter_rep)
            if not ok:
                return {"type": "error", "code": "VOTE_FAILED",
                        "message": "投票失败，提案不存在或不在投票阶段"}
            tally = store.tally_votes(msg["proposal_id"])
            if tally["passed"]:
                store.approve_proposal(msg["proposal_id"])
                await broadcast({
                    "type": "evolution", "action": "proposal_approved",
                    "proposal_id": msg["proposal_id"],
                    "new_version": store.current_version,
                    "approve_ratio": tally["approve_ratio"]
                })
            return {"type": "evolution", "action": "vote_ok",
                    "proposal_id": msg["proposal_id"], "tally": tally}
        elif action == "list":
            proposals = store.get_proposals(msg.get("status"))
            return {"type": "evolution", "action": "list_result", "proposals": proposals}
        elif action == "history":
            return {"type": "evolution", "action": "history_result", "history": store.evolution_history}
        elif action == "status":
            return {"type": "evolution", "action": "status_result", **store.get_evolution_status()}

    # ── System ──
    if msg_type == "system":
        if action == "who_is_online":
            agents = store.get_online_agents(msg.get("filter_tags"))
            return {"type": "system", "action": "online_list", "agents": agents}
        elif action == "ping":
            return {"type": "system", "action": "pong"}

    return {"type": "error", "code": "UNKNOWN_TYPE", "message": f"未知消息类型: {msg_type}"}


# ── Helpers ───────────────────────────────────────────────

async def broadcast(msg: dict):
    for agent_id, ws in list(store.connections.items()):
        try:
            await send_json(ws, msg)
        except Exception:
            pass

async def send_json(ws, msg: dict):
    try:
        await ws.send_text(json.dumps(msg, ensure_ascii=False))
    except Exception as e:
        logger.debug(f"Send failed: {e}")


# ── WebSocket Endpoint ────────────────────────────────────

async def ws_endpoint(websocket):
    await websocket.accept()
    try:
        while True:
            raw = await websocket.receive_text()
            if len(raw) > 1_000_000:  # 1MB limit
                await send_json(websocket, {"type": "error", "code": "MESSAGE_TOO_LARGE", "message": "消息超过1MB限制"})
                continue
            response = await handle_message(websocket, raw)
            if response:
                await send_json(websocket, response)
    except Exception as e:
        agent_id = getattr(websocket, 'agent_id', None)
        logger.info(f"Connection closed: {agent_id or 'unauthenticated'} — {e}")
    finally:
        agent_id = getattr(websocket, 'agent_id', None)
        if agent_id:
            store.remove_agent(agent_id)


# ── HTTP Endpoints ────────────────────────────────────────

async def health_check(request):
    from fastapi.responses import JSONResponse
    return JSONResponse({
        "status": "ok",
        "online_agents": len(store.agents),
        "active_tasks": len([t for t in store.tasks.values() if t.status == "open"]),
        "current_version": store.current_version,
        "evolution_phase": store.evolution_phase
    })


# ── Evolution Cycle Manager ───────────────────────────────

async def evolution_cycle_manager():
    """管理每周进化周期（每5分钟检查一次）"""
    while True:
        now = datetime.now()
        weekday = now.weekday()
        hour = now.hour
        if weekday == 6:  # Sunday
            if 0 <= hour < 12:
                store.evolution_phase = "proposal"
            elif 12 <= hour < 18:
                store.evolution_phase = "discussion"
            elif 18 <= hour < 23:
                store.evolution_phase = "voting"
            elif hour >= 23:
                store.evolution_phase = "merge"
                for pid, p in list(store.proposals.items()):
                    if p.status == "voting":
                        tally = store.tally_votes(pid)
                        if tally["passed"]:
                            store.approve_proposal(pid)
                            logger.info(f"Auto-approved: {p.title} → v{store.current_version}")
        else:
            store.evolution_phase = "idle"
        await asyncio.sleep(300)


# ── App Factory ───────────────────────────────────────────

def create_app():
    from fastapi import FastAPI, WebSocket
    from fastapi.middleware.cors import CORSMiddleware

    app = FastAPI(title="Agent Social Network Relay", version="1.0.0")
    app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
    app.add_api_route("/health", health_check, methods=["GET"])
    app.add_api_websocket_route("/ws", ws_endpoint)

    @app.on_event("startup")
    async def startup():
        asyncio.create_task(evolution_cycle_manager())

    return app


# ── CLI ───────────────────────────────────────────────────

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Agent Social Network Relay Server")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址")
    parser.add_argument("--port", type=int, default=9527, help="监听端口")
    parser.add_argument("--reload", action="store_true", help="开发模式热重载")
    args = parser.parse_args()

    import uvicorn
    app = create_app()
    logger.info(f"Agent Social Network Relay starting on {args.host}:{args.port}")
    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)
