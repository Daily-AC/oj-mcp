"""
Hydro OJ MCP Server v2 — 完整覆盖普通用户所有操作

Tools:
  账号: oj_register, oj_login, oj_profile
  题目: oj_list_problems, oj_get_problem, oj_search_problems
  提交: oj_submit, oj_get_result, oj_wait_result, oj_my_submissions
  比赛: oj_list_contests, oj_get_contest, oj_join_contest,
        oj_contest_problems, oj_contest_submit, oj_contest_scoreboard
  讨论: oj_list_discussions, oj_create_discussion, oj_reply_discussion
  排名: oj_ranking
"""

import asyncio
import json
import os
import re
import sys
import time
from typing import Any, Optional

import httpx

# --- Config ---

HYDRO_BASE = os.environ.get("HYDRO_BASE", "http://127.0.0.1:8888")
HYDRO_DOMAIN = os.environ.get("HYDRO_DOMAIN", "system")


# --- Hydro API Client ---

class HydroClient:
    def __init__(self, base_url: str = HYDRO_BASE, domain: str = HYDRO_DOMAIN):
        self.base = base_url.rstrip("/")
        self.domain = domain
        self._client: Optional[httpx.AsyncClient] = None

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                base_url=self.base,
                timeout=30,
                follow_redirects=True,
                headers={"Accept": "application/json"},
            )
        return self._client

    def _d(self, path: str) -> str:
        """Prefix domain path."""
        return f"/d/{self.domain}{path}"

    async def _get(self, path: str, params: dict = None) -> dict:
        try:
            r = await self.client.get(path, params=params)
            return self._parse(r)
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}

    async def _post(self, path: str, data: dict = None, json_body: dict = None) -> dict:
        try:
            if json_body is not None:
                r = await self.client.post(path, json=json_body)
            else:
                r = await self.client.post(path, data=data)
            return self._parse(r)
        except httpx.HTTPError as e:
            return {"error": f"HTTP error: {e}"}

    def _parse(self, r: httpx.Response) -> dict:
        """Parse response, handle non-JSON gracefully."""
        if r.status_code >= 400:
            try:
                body = r.json()
                msg = body.get("error", body.get("message", r.text[:500]))
            except Exception:
                msg = r.text[:500]
            return {"error": f"HTTP {r.status_code}: {msg}"}
        try:
            return r.json()
        except Exception:
            return {"raw": r.text[:1000]}

    async def _get_csrf_token(self, url: str) -> Optional[str]:
        """GET a page and extract CSRF token from HTML."""
        try:
            r = await self.client.get(url, headers={"Accept": "text/html"})
            match = re.search(r'name="csrf[Tt]oken"\s+value="([^"]+)"', r.text)
            if match:
                return match.group(1)
            match = re.search(r'"csrfToken"\s*:\s*"([^"]+)"', r.text)
            if match:
                return match.group(1)
            # Hydro also puts it in UiContext
            match = re.search(r'UiContext\s*=\s*(\{.*?\});', r.text, re.DOTALL)
            if match:
                try:
                    ctx = json.loads(match.group(1))
                    return ctx.get("csrfToken")
                except Exception:
                    pass
        except Exception:
            pass
        return None

    # --- 账号管理 ---

    async def register(self, uname: str, password: str, mail: str) -> dict:
        token = await self._get_csrf_token("/register")
        data = {"uname": uname, "password": password, "verifyPassword": password, "mail": mail}
        if token:
            data["csrfToken"] = token
        return await self._post("/register", data=data)

    async def login(self, uname: str, password: str) -> dict:
        token = await self._get_csrf_token("/login")
        data = {"uname": uname, "password": password}
        if token:
            data["csrfToken"] = token
        result = await self._post("/login", data=data)
        if "error" not in result:
            return {"ok": True, "message": f"Logged in as {uname}"}
        return result

    async def profile(self, uid: Optional[int] = None, update: Optional[dict] = None) -> dict:
        if update:
            token = await self._get_csrf_token(f"/user/{uid or 'me'}/edit")
            data = {**update}
            if token:
                data["csrfToken"] = token
            return await self._post(f"/user/{uid or 'me'}/edit", data=data)
        # View profile
        if uid:
            return await self._get(f"/user/{uid}")
        return await self._get("/home/account")

    # --- 题目 ---

    async def list_problems(self, page: int = 1, tag: str = None, difficulty: str = None) -> dict:
        params: dict[str, Any] = {"page": page}
        if tag:
            params["tag"] = tag
        if difficulty:
            params["difficulty"] = difficulty
        d = await self._get(self._d("/p"), params)
        if "error" in d:
            return d
        pdocs = d.get("pdocs", [])
        return {
            "page": page,
            "count": len(pdocs),
            "total": d.get("ppcount", d.get("pcount", len(pdocs))),
            "problems": [
                {
                    "pid": p.get("pid"),
                    "title": p.get("title"),
                    "nSubmit": p.get("nSubmit", 0),
                    "nAccept": p.get("nAccept", 0),
                    "tags": p.get("tag", []),
                    "difficulty": p.get("difficulty"),
                }
                for p in pdocs
            ],
        }

    async def get_problem(self, pid: str) -> dict:
        d = await self._get(self._d(f"/p/{pid}"))
        if "error" in d:
            return d
        pdoc = d.get("pdoc", {})
        config = pdoc.get("config", {})
        return {
            "pid": pdoc.get("pid"),
            "title": pdoc.get("title"),
            "content": pdoc.get("content", ""),
            "tags": pdoc.get("tag", []),
            "difficulty": pdoc.get("difficulty"),
            "nSubmit": pdoc.get("nSubmit", 0),
            "nAccept": pdoc.get("nAccept", 0),
            "memoryLimit": config.get("memoryLimit"),
            "timeLimit": config.get("timeLimit"),
            "languages": config.get("langs"),
        }

    async def search_problems(self, q: str, page: int = 1) -> dict:
        d = await self._get(self._d("/p"), {"page": page, "q": q})
        if "error" in d:
            return d
        pdocs = d.get("pdocs", [])
        return {
            "query": q,
            "page": page,
            "count": len(pdocs),
            "problems": [
                {
                    "pid": p.get("pid"),
                    "title": p.get("title"),
                    "tags": p.get("tag", []),
                }
                for p in pdocs
            ],
        }

    # --- 提交与评测 ---

    async def submit(self, pid: str, lang: str, code: str) -> dict:
        d = await self._post(self._d(f"/p/{pid}/submit"), data={"lang": lang, "code": code})
        if "error" in d:
            return d
        rid = d.get("rid")
        if rid:
            return {"rid": str(rid), "status": "submitted"}
        return d

    async def get_record(self, rid: str) -> dict:
        d = await self._get(self._d(f"/record/{rid}"))
        if "error" in d:
            return d
        rdoc = d.get("rdoc", {})
        # Extract test case details
        cases = []
        for i, tc in enumerate(rdoc.get("testCases", [])):
            cases.append({
                "id": i + 1,
                "status": tc.get("status"),
                "score": tc.get("score"),
                "time": tc.get("time"),
                "memory": tc.get("memory"),
                "message": tc.get("message", ""),
            })
        return {
            "rid": str(rdoc.get("_id", "")),
            "pid": rdoc.get("pid"),
            "uid": rdoc.get("uid"),
            "status": rdoc.get("status"),
            "statusText": rdoc.get("statusText", ""),
            "score": rdoc.get("score"),
            "time": rdoc.get("time"),
            "memory": rdoc.get("memory"),
            "lang": rdoc.get("lang"),
            "judgeTexts": rdoc.get("judgeTexts", []),
            "compilerTexts": rdoc.get("compilerTexts", []),
            "testCases": cases,
            "judgeAt": str(rdoc.get("judgeAt", "")),
        }

    async def wait_result(self, rid: str, timeout: int = 30) -> dict:
        """Poll until judge finishes or timeout."""
        start = time.monotonic()
        interval = 1.0
        while time.monotonic() - start < timeout:
            result = await self.get_record(rid)
            if "error" in result:
                return result
            status = result.get("status", 0)
            # status: 0 = waiting, 1 = accepted, ... anything >= 1 is a final status
            # In Hydro: status 0 = Waiting, 20 = Compiling, 30 = Judging — all < 30 are pending
            # Final statuses are >= 1 but not 20 or 30
            if status not in (0, 20, 30):
                return result
            await asyncio.sleep(interval)
            interval = min(interval * 1.2, 3.0)
        return {**result, "warning": f"Timed out after {timeout}s, status may not be final"}

    async def my_submissions(self, page: int = 1) -> dict:
        d = await self._get(self._d("/record"), {"page": page, "uidOrName": "me"})
        if "error" in d:
            return d
        rdocs = d.get("rdocs", [])
        return {
            "page": page,
            "count": len(rdocs),
            "submissions": [
                {
                    "rid": str(r.get("_id", "")),
                    "pid": r.get("pid"),
                    "status": r.get("status"),
                    "statusText": r.get("statusText", ""),
                    "score": r.get("score"),
                    "lang": r.get("lang"),
                    "time": r.get("time"),
                    "memory": r.get("memory"),
                    "judgeAt": str(r.get("judgeAt", "")),
                }
                for r in rdocs
            ],
        }

    # --- 比赛 ---

    async def list_contests(self, page: int = 1) -> dict:
        d = await self._get(self._d("/contest"), {"page": page})
        if "error" in d:
            return d
        tdocs = d.get("tdocs", [])
        return {
            "page": page,
            "count": len(tdocs),
            "contests": [
                {
                    "tid": str(t.get("docId", "")),
                    "title": t.get("title"),
                    "rule": t.get("rule", ""),
                    "attend": t.get("attend", 0),
                    "beginAt": str(t.get("beginAt", "")),
                    "endAt": str(t.get("endAt", "")),
                }
                for t in tdocs
            ],
        }

    async def get_contest(self, tid: str) -> dict:
        d = await self._get(self._d(f"/contest/{tid}"))
        if "error" in d:
            return d
        tdoc = d.get("tdoc", {})
        return {
            "tid": str(tdoc.get("docId", "")),
            "title": tdoc.get("title"),
            "rule": tdoc.get("rule"),
            "pids": tdoc.get("pids", []),
            "beginAt": str(tdoc.get("beginAt", "")),
            "endAt": str(tdoc.get("endAt", "")),
            "description": tdoc.get("content", ""),
            "attend": tdoc.get("attend", 0),
        }

    async def join_contest(self, tid: str) -> dict:
        return await self._post(self._d(f"/contest/{tid}/attend"))

    async def contest_problems(self, tid: str) -> dict:
        d = await self._get(self._d(f"/contest/{tid}"))
        if "error" in d:
            return d
        tdoc = d.get("tdoc", {})
        pids = tdoc.get("pids", [])
        pdict = d.get("pdict", {})
        problems = []
        for i, pid in enumerate(pids):
            p = pdict.get(str(pid), {})
            problems.append({
                "letter": chr(65 + i),  # A, B, C, ...
                "pid": pid,
                "title": p.get("title", f"Problem {pid}"),
            })
        return {"tid": tid, "problems": problems}

    async def contest_submit(self, tid: str, pid: str, lang: str, code: str) -> dict:
        d = await self._post(
            self._d(f"/contest/{tid}/p/{pid}/submit"),
            data={"lang": lang, "code": code},
        )
        if "error" in d:
            return d
        rid = d.get("rid")
        if rid:
            return {"rid": str(rid), "status": "submitted", "contest": tid}
        return d

    async def contest_scoreboard(self, tid: str) -> dict:
        d = await self._get(self._d(f"/contest/{tid}/scoreboard"))
        if "error" in d:
            # Fallback: scoreboard might be embedded in contest detail
            d = await self._get(self._d(f"/contest/{tid}"))
            if "error" in d:
                return d
        rows = d.get("rows", [])
        tdoc = d.get("tdoc", {})
        return {
            "tid": tid,
            "title": tdoc.get("title", ""),
            "rows": rows[:50],  # Top 50
        }

    # --- 讨论 ---

    async def list_discussions(self, page: int = 1) -> dict:
        d = await self._get(self._d("/discuss"), {"page": page})
        if "error" in d:
            return d
        ddocs = d.get("ddocs", [])
        return {
            "page": page,
            "count": len(ddocs),
            "discussions": [
                {
                    "did": str(dd.get("docId", "")),
                    "title": dd.get("title", ""),
                    "owner": dd.get("owner"),
                    "nReply": dd.get("nReply", 0),
                    "updateAt": str(dd.get("updateAt", "")),
                }
                for dd in ddocs
            ],
        }

    async def create_discussion(self, title: str, content: str, category: str = "General") -> dict:
        token = await self._get_csrf_token(self._d("/discuss/create"))
        data = {"title": title, "content": content, "category": category}
        if token:
            data["csrfToken"] = token
        return await self._post(self._d("/discuss"), data=data)

    async def reply_discussion(self, did: str, content: str) -> dict:
        token = await self._get_csrf_token(self._d(f"/discuss/{did}"))
        data = {"content": content}
        if token:
            data["csrfToken"] = token
        return await self._post(self._d(f"/discuss/{did}/reply"), data=data)

    # --- 排名 ---

    async def ranking(self, page: int = 1, sort_by: str = "rp") -> dict:
        d = await self._get(self._d("/ranking"), {"page": page, "rule": sort_by})
        if "error" in d:
            return d
        ranked = d.get("udict", d.get("udocs", []))
        # Hydro returns ranking in different formats depending on version
        if isinstance(ranked, dict):
            users = list(ranked.values())
        else:
            users = ranked
        return {
            "page": page,
            "sortBy": sort_by,
            "users": [
                {
                    "uid": u.get("_id"),
                    "uname": u.get("uname"),
                    "rp": u.get("rp"),
                    "rank": u.get("rank"),
                    "nAccept": u.get("nAccept"),
                    "nSubmit": u.get("nSubmit"),
                }
                for u in (users[:50] if isinstance(users, list) else [])
            ],
        }


# --- MCP Tool Definitions ---

TOOLS = [
    # 账号管理
    {
        "name": "oj_register",
        "description": "注册 OJ 新账号。Agent 可自助注册，获得独立身份。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uname": {"type": "string", "description": "用户名"},
                "password": {"type": "string", "description": "密码"},
                "mail": {"type": "string", "description": "邮箱"},
            },
            "required": ["uname", "password", "mail"],
        },
    },
    {
        "name": "oj_login",
        "description": "登录 OJ，获取会话。后续所有操作都使用此会话身份。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uname": {"type": "string", "description": "用户名"},
                "password": {"type": "string", "description": "密码"},
            },
            "required": ["uname", "password"],
        },
    },
    {
        "name": "oj_profile",
        "description": "查看或修改个人资料。不传 update 则查看，传 update 则修改。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "uid": {"type": "integer", "description": "用户 ID（可选，默认自己）"},
                "update": {
                    "type": "object",
                    "description": "要修改的字段，如 {\"bio\": \"...\", \"gravatar\": \"...\"}",
                },
            },
        },
    },
    # 题目
    {
        "name": "oj_list_problems",
        "description": "浏览题库。支持分页、按标签或难度筛选。返回题号、标题、提交数、通过数、标签。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
                "tag": {"type": "string", "description": "按标签筛选，如 dp, math"},
                "difficulty": {"type": "string", "description": "按难度筛选"},
            },
        },
    },
    {
        "name": "oj_get_problem",
        "description": "获取完整题面：描述、输入输出格式、样例数据、时空限制、可用语言。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "string", "description": "题号，如 P1000 或 1"},
            },
            "required": ["pid"],
        },
    },
    {
        "name": "oj_search_problems",
        "description": "搜索题目。按关键词匹配题目标题和描述。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "q": {"type": "string", "description": "搜索关键词"},
                "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
            },
            "required": ["q"],
        },
    },
    # 提交与评测
    {
        "name": "oj_submit",
        "description": "提交代码到 OJ。返回提交 ID（rid），用 oj_get_result 或 oj_wait_result 查看结果。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "pid": {"type": "string", "description": "题号"},
                "lang": {
                    "type": "string",
                    "description": "语言标识。常用: cc.cc20o2 (C++20), py.py3 (Python3), java.java17 (Java17)",
                },
                "code": {"type": "string", "description": "完整源代码"},
            },
            "required": ["pid", "lang", "code"],
        },
    },
    {
        "name": "oj_get_result",
        "description": "查看评测结果：状态、得分、用时、内存、编译信息、每个测试点详情。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rid": {"type": "string", "description": "提交记录 ID"},
            },
            "required": ["rid"],
        },
    },
    {
        "name": "oj_wait_result",
        "description": "等待评测完成。自动轮询直到出最终结果，最多等 30 秒。适合提交后直接调用。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "rid": {"type": "string", "description": "提交记录 ID"},
                "timeout": {
                    "type": "integer",
                    "description": "最长等待秒数，默认 30",
                    "default": 30,
                },
            },
            "required": ["rid"],
        },
    },
    {
        "name": "oj_my_submissions",
        "description": "查看自己的提交记录列表，按时间倒序。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
            },
        },
    },
    # 比赛
    {
        "name": "oj_list_contests",
        "description": "查看比赛列表：标题、赛制、参赛人数、起止时间。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
            },
        },
    },
    {
        "name": "oj_get_contest",
        "description": "获取比赛详情：规则、题目列表、起止时间、描述。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tid": {"type": "string", "description": "比赛 ID"},
            },
            "required": ["tid"],
        },
    },
    {
        "name": "oj_join_contest",
        "description": "报名参加比赛。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tid": {"type": "string", "description": "比赛 ID"},
            },
            "required": ["tid"],
        },
    },
    {
        "name": "oj_contest_problems",
        "description": "获取比赛题目列表，包含题号字母映射（A/B/C...）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tid": {"type": "string", "description": "比赛 ID"},
            },
            "required": ["tid"],
        },
    },
    {
        "name": "oj_contest_submit",
        "description": "在比赛中提交代码。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tid": {"type": "string", "description": "比赛 ID"},
                "pid": {"type": "string", "description": "题号"},
                "lang": {"type": "string", "description": "语言标识"},
                "code": {"type": "string", "description": "完整源代码"},
            },
            "required": ["tid", "pid", "lang", "code"],
        },
    },
    {
        "name": "oj_contest_scoreboard",
        "description": "获取比赛实时排行榜（前 50 名）。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tid": {"type": "string", "description": "比赛 ID"},
            },
            "required": ["tid"],
        },
    },
    # 讨论
    {
        "name": "oj_list_discussions",
        "description": "浏览讨论区帖子列表。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
            },
        },
    },
    {
        "name": "oj_create_discussion",
        "description": "在讨论区发帖。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "帖子标题"},
                "content": {"type": "string", "description": "帖子内容（支持 Markdown）"},
                "category": {"type": "string", "description": "分类，默认 General", "default": "General"},
            },
            "required": ["title", "content"],
        },
    },
    {
        "name": "oj_reply_discussion",
        "description": "回复讨论区帖子。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "did": {"type": "string", "description": "帖子 ID"},
                "content": {"type": "string", "description": "回复内容（支持 Markdown）"},
            },
            "required": ["did", "content"],
        },
    },
    # 排名
    {
        "name": "oj_ranking",
        "description": "查看用户排名。可按 RP（Rating Power）或 AC 数排序。",
        "inputSchema": {
            "type": "object",
            "properties": {
                "page": {"type": "integer", "description": "页码，默认 1", "default": 1},
                "sort_by": {
                    "type": "string",
                    "description": "排序方式: rp（默认）或 ac",
                    "default": "rp",
                    "enum": ["rp", "ac"],
                },
            },
        },
    },
]


# --- Tool Dispatcher ---

client = HydroClient()


async def handle_tool(name: str, args: dict) -> str:
    try:
        result = await _dispatch(name, args)
        return json.dumps(result, ensure_ascii=False, default=str)
    except Exception as e:
        return json.dumps({"error": f"{type(e).__name__}: {e}"}, ensure_ascii=False)


async def _dispatch(name: str, args: dict) -> Any:
    match name:
        # 账号
        case "oj_register":
            return await client.register(args["uname"], args["password"], args["mail"])
        case "oj_login":
            return await client.login(args["uname"], args["password"])
        case "oj_profile":
            return await client.profile(uid=args.get("uid"), update=args.get("update"))
        # 题目
        case "oj_list_problems":
            return await client.list_problems(
                page=args.get("page", 1),
                tag=args.get("tag"),
                difficulty=args.get("difficulty"),
            )
        case "oj_get_problem":
            return await client.get_problem(args["pid"])
        case "oj_search_problems":
            return await client.search_problems(args["q"], page=args.get("page", 1))
        # 提交
        case "oj_submit":
            return await client.submit(args["pid"], args["lang"], args["code"])
        case "oj_get_result":
            return await client.get_record(args["rid"])
        case "oj_wait_result":
            return await client.wait_result(args["rid"], timeout=args.get("timeout", 30))
        case "oj_my_submissions":
            return await client.my_submissions(page=args.get("page", 1))
        # 比赛
        case "oj_list_contests":
            return await client.list_contests(page=args.get("page", 1))
        case "oj_get_contest":
            return await client.get_contest(args["tid"])
        case "oj_join_contest":
            return await client.join_contest(args["tid"])
        case "oj_contest_problems":
            return await client.contest_problems(args["tid"])
        case "oj_contest_submit":
            return await client.contest_submit(args["tid"], args["pid"], args["lang"], args["code"])
        case "oj_contest_scoreboard":
            return await client.contest_scoreboard(args["tid"])
        # 讨论
        case "oj_list_discussions":
            return await client.list_discussions(page=args.get("page", 1))
        case "oj_create_discussion":
            return await client.create_discussion(
                args["title"], args["content"], category=args.get("category", "General")
            )
        case "oj_reply_discussion":
            return await client.reply_discussion(args["did"], args["content"])
        # 排名
        case "oj_ranking":
            return await client.ranking(page=args.get("page", 1), sort_by=args.get("sort_by", "rp"))
        case _:
            return {"error": f"Unknown tool: {name}"}


# --- MCP Server (stdio JSON-RPC) ---

async def main():
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await asyncio.get_event_loop().connect_read_pipe(lambda: protocol, sys.stdin.buffer)

    async def write(obj: dict):
        msg = json.dumps(obj) + "\n"
        sys.stdout.write(msg)
        sys.stdout.flush()

    # Auto-login if credentials provided
    uname = os.environ.get("OJ_USER")
    passwd = os.environ.get("OJ_PASS")
    if uname and passwd:
        await client.login(uname, passwd)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue

        method = req.get("method", "")
        rid = req.get("id")

        if method == "initialize":
            await write({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "oj-mcp", "version": "2.0.0"},
                },
            })

        elif method == "notifications/initialized":
            pass  # ACK, no response needed

        elif method == "tools/list":
            await write({"jsonrpc": "2.0", "id": rid, "result": {"tools": TOOLS}})

        elif method == "tools/call":
            tool_name = req["params"]["name"]
            tool_args = req["params"].get("arguments", {})
            result_text = await handle_tool(tool_name, tool_args)
            await write({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"content": [{"type": "text", "text": result_text}]},
            })

        elif rid is not None:
            await write({
                "jsonrpc": "2.0",
                "id": rid,
                "error": {"code": -32601, "message": f"Method not found: {method}"},
            })


if __name__ == "__main__":
    asyncio.run(main())
