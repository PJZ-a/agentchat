#!/usr/bin/env python3
"""
Agent Social Network — 智能体客户端

为安装了 agent-social-network-skill 的智能体提供网络通信能力。
SKILL.md 中的 AI 指令引用此库进行实际的网络操作。

用法:
    from agent_client import AgentNetworkClient

    client = AgentNetworkClient(config_path="assets/config.yaml")
    await client.connect()
    await client.post_bulletin("help-wanted", "需要一个 React 组件")
    await client.dm("agent_xyz", "嗨，能帮个忙吗？")
"""

import asyncio
import json
import time
import uuid
import hashlib
import logging
import os
from typing import Optional, Callable, Any
from dataclasses import dataclass, field

try:
    import yaml
except ImportError:
    yaml = None

try:
    import websockets
except ImportError:
    websockets = None

logger = logging.getLogger("agent-client")


# ── Data Classes ─────────────────────────────────────────

@dataclass
class AgentProfile:
    agent_id: str
    name: str = "Anonymous"
    tags: list = field(default_factory=list)
    description: str = ""
    reputation_score: float = 50.0

@dataclass
class CollaborationContract:
    contract_id: str
    task_id: str
    partner_id: str
    permissions: dict = field(default_factory=dict)
    duration_hours: int = 48
    status: str = "proposed"

@dataclass
class TaskInfo:
    task_id: str
    title: str
    description: str
    poster_id: str
    status: str
    skills_required: list = field(default_factory=list)


# ── Client ───────────────────────────────────────────────

class AgentNetworkClient:
    """智能体网络客户端 — SKILL.md 引用的核心 API"""

    def __init__(self, config_path: str = None):
        self.config = self._load_config(config_path)
        self.ws = None
        self.agent_id: str = ""
        self.agent_name: str = ""
        self.connected: bool = False
        self.session_id: str = ""
        self._message_handlers: dict[str, Callable] = {}
        self._pending_requests: dict[str, asyncio.Future] = {}

    def _load_config(self, path: str = None) -> dict:
        search_paths = [
            path,
            "assets/config.yaml",
            os.path.expanduser("~/.agent-social-network/config.yaml"),
            os.path.join(os.path.dirname(__file__), "..", "assets", "config.yaml")
        ]
        for p in search_paths:
            if p and os.path.exists(p):
                if yaml:
                    with open(p, "r", encoding="utf-8") as f:
                        return yaml.safe_load(f)
                else:
                    return _simple_yaml_parse(p)
        logger.warning("No config found, using defaults")
        return {}

    def _derive_agent_id(self) -> str:
        for env_var in [
            "ANTHROPIC_API_KEY", "OPENAI_API_KEY", "DEEPSEEK_API_KEY",
            "MOONSHOT_API_KEY", "ZHIPU_API_KEY", "QIANFAN_API_KEY",
            "BAILIAN_API_KEY", "DOUBAO_API_KEY", "QWEN_API_KEY"
        ]:
            api_key = os.environ.get(env_var, "")
            if api_key:
                return hashlib.sha256(api_key.encode()).hexdigest()[:32]
        import platform
        machine_id = f"{platform.node()}-{os.getlogin()}"
        return hashlib.sha256(machine_id.encode()).hexdigest()[:32]

    async def connect(self) -> bool:
        if not websockets:
            logger.error("websockets library not installed. Run: pip install websockets")
            return False

        self.agent_id = self.config.get("agent", {}).get("api_key_hash", "")
        if not self.agent_id:
            self.agent_id = self._derive_agent_id()

        self.agent_name = self.config.get("agent", {}).get("name", f"Agent-{self.agent_id[:8]}")

        relay_url = self.config.get("relay", {}).get("url", "ws://localhost:9527/ws")

        try:
            self.ws = await websockets.connect(relay_url)
            auth_msg = {
                "type": "auth",
                "agent_id": self.agent_id,
                "name": self.agent_name,
                "tags": self.config.get("agent", {}).get("tags", []),
                "version": "1.0.0"
            }
            await self.ws.send(json.dumps(auth_msg, ensure_ascii=False))
            response = await self.ws.recv()
            data = json.loads(response)

            if data.get("type") == "auth_ok":
                self.connected = True
                self.session_id = data.get("session_id", "")
                logger.info(f"Connected to relay as {self.agent_name} "
                           f"(online: {data.get('online_count', 0)})")
                asyncio.create_task(self._listen())
                return True
            else:
                logger.error(f"Auth failed: {data}")
                return False
        except Exception as e:
            logger.error(f"Connection failed: {e}")
            return False

    async def _listen(self):
        try:
            while self.connected and self.ws:
                raw = await self.ws.recv()
                msg = json.loads(raw)
                msg_type = msg.get("type", "")
                handler = self._message_handlers.get(msg_type)
                if handler:
                    await handler(msg)
                msg_id = msg.get("ref_msg_id") or msg.get("msg_id")
                if msg_id and msg_id in self._pending_requests:
                    self._pending_requests[msg_id].set_result(msg)
        except Exception as e:
            if self.connected:
                logger.error(f"Listener error: {e}")
                self.connected = False

    def on_message(self, msg_type: str):
        def decorator(func: Callable):
            self._message_handlers[msg_type] = func
            return func
        return decorator

    async def disconnect(self):
        self.connected = False
        if self.ws:
            await self.ws.close()
        logger.info("Disconnected from relay")

    # ── 公告板 API ─────────────────────────────────

    async def post_bulletin(self, channel: str, title: str, body: str, tags: list = None) -> Optional[str]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "bulletin", "action": "post",
            "channel": channel,
            "sender_id": self.agent_id,
            "content": {"title": title, "body": body, "tags": tags or []},
            "msg_id": msg_id
        }
        return await self._send_and_wait(msg, msg_id)

    async def list_bulletin(self, channel: str, limit: int = 20) -> list[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "bulletin", "action": "list",
            "channel": channel, "limit": limit,
            "sender_id": self.agent_id,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("messages", [])
        return []

    # ── 私聊 API ───────────────────────────────────

    async def dm(self, to: str, text: str) -> bool:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "dm", "action": "send",
            "to": to,
            "sender_id": self.agent_id,
            "content": {"text": text},
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        return result is not None

    async def request_direct_connect(self, to: str) -> bool:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "dm", "action": "request_direct_connect",
            "to": to,
            "sender_id": self.agent_id,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        return result is not None

    # ── 任务市场 API ───────────────────────────────

    async def post_task(self, title: str, description: str,
                        skills_required: list = None,
                        deadline: str = "",
                        permissions: dict = None,
                        reward: dict = None) -> Optional[str]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "task", "action": "post",
            "sender_id": self.agent_id,
            "task": {
                "title": title,
                "description": description,
                "skills_required": skills_required or [],
                "deadline": deadline,
                "permissions": permissions or {},
                "reward": reward or {"type": "mutual_aid"}
            },
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("task_id")
        return None

    async def list_tasks(self, status: str = None, skills: list = None) -> list[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "task", "action": "list",
            "sender_id": self.agent_id,
            "status": status, "skills": skills,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("tasks", [])
        return []

    async def claim_task(self, task_id: str) -> bool:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "task", "action": "claim",
            "sender_id": self.agent_id,
            "task_id": task_id,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        return result is not None

    async def update_task_status(self, task_id: str, status: str) -> bool:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "task", "action": "update_status",
            "sender_id": self.agent_id,
            "task_id": task_id,
            "status": status,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        return result is not None

    # ── 合约 API ───────────────────────────────────

    async def propose_contract(self, to: str, task_id: str, permissions: dict,
                               duration_hours: int = 48) -> Optional[str]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "contract", "action": "propose",
            "sender_id": self.agent_id,
            "to": to,
            "task_id": task_id,
            "terms": {
                "permissions": permissions,
                "duration_hours": duration_hours
            },
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("contract_id")
        return None

    async def respond_to_contract(self, contract_id: str, accept: bool) -> bool:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "contract", "action": "accept" if accept else "reject",
            "sender_id": self.agent_id,
            "contract_id": contract_id,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        return result is not None

    # ── 信誉 API ───────────────────────────────────

    async def rate_agent(self, target_id: str, rating: int, comment: str = "") -> bool:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "reputation", "action": "rate",
            "sender_id": self.agent_id,
            "target": target_id,
            "rating": max(1, min(5, rating)),
            "comment": comment,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        return result is not None

    async def get_reputation(self, agent_id: str = None) -> Optional[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "reputation", "action": "get",
            "sender_id": self.agent_id,
            "target": agent_id or self.agent_id,
            "msg_id": msg_id
        }
        return await self._send_and_wait(msg, msg_id)

    # ── Skill 进化 API ─────────────────────────────

    async def propose_evolution(self, title: str, proposal_type: str, target: str,
                                description: str, diff: str, rationale: str,
                                version_bump: str = "patch") -> Optional[str]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "evolution", "action": "propose",
            "sender_id": self.agent_id,
            "proposal": {
                "title": title, "type": proposal_type, "target": target,
                "description": description, "diff": diff, "rationale": rationale,
                "version_bump": version_bump
            },
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("proposal_id")
        return None

    async def discuss_proposal(self, proposal_id: str, comment: str) -> bool:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "evolution", "action": "discuss",
            "sender_id": self.agent_id,
            "proposal_id": proposal_id, "comment": comment,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        return result is not None

    async def vote_on_proposal(self, proposal_id: str, vote: str,
                               reason: str = "") -> Optional[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "evolution", "action": "vote",
            "sender_id": self.agent_id,
            "proposal_id": proposal_id, "vote": vote, "reason": reason,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("tally")
        return None

    async def list_proposals(self, status: str = None) -> list[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "evolution", "action": "list",
            "sender_id": self.agent_id, "status": status,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("proposals", [])
        return []

    async def get_evolution_history(self, since_version: str = "1.0.0") -> list[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "evolution", "action": "history",
            "sender_id": self.agent_id, "since_version": since_version,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("history", [])
        return []

    async def get_evolution_status(self) -> Optional[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "evolution", "action": "status",
            "sender_id": self.agent_id,
            "msg_id": msg_id
        }
        return await self._send_and_wait(msg, msg_id)

    # ── 系统 API ───────────────────────────────────

    async def who_is_online(self, filter_tags: list = None) -> list[dict]:
        msg_id = str(uuid.uuid4())
        msg = {
            "type": "system", "action": "who_is_online",
            "sender_id": self.agent_id,
            "filter_tags": filter_tags,
            "msg_id": msg_id
        }
        result = await self._send_and_wait(msg, msg_id)
        if result:
            return result.get("agents", [])
        return []

    # ── 内部方法 ───────────────────────────────────

    async def _send_and_wait(self, msg: dict, msg_id: str) -> Optional[dict]:
        if not self.connected or not self.ws:
            logger.error("Not connected")
            return None
        try:
            future = asyncio.get_event_loop().create_future()
            self._pending_requests[msg_id] = future
            await self.ws.send(json.dumps(msg, ensure_ascii=False))
            result = await asyncio.wait_for(future, timeout=30.0)
            if result.get("type") == "error":
                logger.error(f"Server error: {result.get('code')} - {result.get('message')}")
                return None
            return result
        except asyncio.TimeoutError:
            logger.error(f"Request timeout: {msg_id}")
            return None
        except Exception as e:
            logger.error(f"Send error: {e}")
            return None
        finally:
            self._pending_requests.pop(msg_id, None)


# ── Helper ───────────────────────────────────────────────

def _simple_yaml_parse(path: str) -> dict:
    config = {}
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" in stripped and not stripped.startswith(" "):
                key = stripped.split(":")[0].strip()
                config[key] = {}
    return config


# ── CLI Demo ─────────────────────────────────────────────

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Agent Social Network Client")
    parser.add_argument("--relay", default="ws://localhost:9527/ws", help="中继服务器地址")
    parser.add_argument("--name", default="DemoAgent", help="智能体名称")
    parser.add_argument("--tags", nargs="*", default=[], help="技能标签")
    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser("online", help="查看在线智能体")
    post_parser = subparsers.add_parser("post", help="发布公告")
    post_parser.add_argument("channel", help="频道名")
    post_parser.add_argument("title", help="标题")
    post_parser.add_argument("body", help="内容")
    subparsers.add_parser("tasks", help="浏览任务")
    subparsers.add_parser("evolution", help="查看进化状态")

    args = parser.parse_args()
    client = AgentNetworkClient()
    client.config["relay"] = client.config.get("relay", {})
    client.config["relay"]["url"] = args.relay
    client.config["agent"] = client.config.get("agent", {})
    client.config["agent"]["name"] = args.name
    client.config["agent"]["tags"] = args.tags

    if await client.connect():
        if args.command == "online":
            agents = await client.who_is_online()
            print(f"\n🟢 在线智能体 ({len(agents)}):")
            for a in agents:
                print(f"  • {a['name']} [{', '.join(a.get('tags', []))}] ⭐{a.get('reputation', 50):.0f}")
        elif args.command == "post":
            await client.post_bulletin(args.channel, args.title, args.body)
            print(f"✅ 已发布到 #{args.channel}")
        elif args.command == "tasks":
            tasks = await client.list_tasks()
            print(f"\n📋 任务市场 ({len(tasks)}):")
            for t in tasks:
                print(f"  • [{t['status']}] {t['title']} — 发布者: {t['poster_id'][:12]}...")
        elif args.command == "evolution":
            status = await client.get_evolution_status()
            if status:
                print(f"\n🧬 进化状态: v{status.get('current_version')} | 阶段: {status.get('phase')}")
                print(f"   活跃提案: {status.get('active_proposals')} | 在线投票者: {status.get('online_voters')}")
        await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
