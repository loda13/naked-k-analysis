from __future__ import annotations

import json
import os
import re
from datetime import date
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup


DEFAULT_WSS_URLS = {
    "research_semiconductor.html": "https://wall-street-skill.com/research/semiconductor",
    "market_risk.html": "https://wall-street-skill.com/ai%E6%B3%A1%E6%B2%AB%E5%91%A8%E6%8A%A5/",
    "earnings.html": "https://wall-street-skill.com/earnings/",
}


def _clean(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalize_header(value: str) -> str:
    text = _clean(value).lower().replace(" ", "").replace("_", "")
    aliases = {
        "ticker": "ticker",
        "symbol": "ticker",
        "代码": "ticker",
        "股票代码": "ticker",
        "排名": "rank",
        "rank": "rank",
        "分数": "score",
        "得分": "score",
        "score": "score",
        "证据": "evidence",
        "证据完整度": "evidence",
        "evidence": "evidence",
        "评级": "rating",
        "结论": "rating",
        "rating": "rating",
        "行业": "sector",
        "板块": "sector",
        "sector": "sector",
        "业务纯度": "business_purity",
        "businesspurity": "business_purity",
        "催化": "catalysts",
        "催化剂": "catalysts",
        "catalysts": "catalysts",
        "风险": "risks",
        "risks": "risks",
        "回避": "avoid",
        "avoid": "avoid",
        "名称": "name",
        "name": "name",
        "状态": "status",
        "status": "status",
        "当前值": "value",
        "数值": "value",
        "value": "value",
        "触发线": "trigger",
        "trigger": "trigger",
        "日期": "date",
        "财报日期": "date",
        "date": "date",
        "时间": "timing",
        "timing": "timing",
        "eps预期": "eps_estimate",
        "eps": "eps_estimate",
        "收入预期": "revenue_estimate",
        "营收预期": "revenue_estimate",
        "revenue": "revenue_estimate",
        "iv隐含波动": "implied_move",
        "隐含波动": "implied_move",
        "impliedmove": "implied_move",
    }
    return aliases.get(text, text)


def _extract_tables(html: str) -> List[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rows: List[Dict[str, str]] = []
    for table in soup.find_all("table"):
        table_rows = table.find_all("tr")
        if not table_rows:
            continue

        header_cells = table_rows[0].find_all(["th", "td"])
        headers = [_normalize_header(cell.get_text(" ", strip=True)) for cell in header_cells]
        if not headers:
            continue

        for tr in table_rows[1:]:
            cells = [_clean(cell.get_text(" ", strip=True)) for cell in tr.find_all(["td", "th"])]
            if not any(cells):
                continue
            rows.append({headers[i]: cells[i] for i in range(min(len(headers), len(cells)))})
    return rows


def _as_of(html: str) -> str:
    match = re.search(r"20\d{2}[-/.年]\d{1,2}[-/.月]\d{1,2}", html)
    if not match:
        return date.today().isoformat()
    raw = match.group(0).replace("年", "-").replace("月", "-").replace("/", "-").replace(".", "-")
    parts = [part for part in raw.split("-") if part]
    if len(parts) >= 3:
        return f"{int(parts[0]):04d}-{int(parts[1]):02d}-{int(parts[2]):02d}"
    return date.today().isoformat()


def _float(value: str) -> Optional[float]:
    match = re.search(r"-?\d+(?:\.\d+)?", value or "")
    if not match:
        return None
    return float(match.group(0))


def _int(value: str) -> Optional[int]:
    number = _float(value)
    if number is None:
        return None
    return int(number)


def _split_values(value: str) -> List[str]:
    return [_clean(part) for part in re.split(r"[/,，、;；]", value or "") if _clean(part)]


def _ticker(value: str) -> str:
    return _clean(value).upper()


def parse_research_html(html: str) -> Dict[str, Any]:
    tickers: Dict[str, Dict[str, Any]] = {}
    avoid: List[str] = []
    for row in _extract_tables(html):
        ticker = _ticker(row.get("ticker", ""))
        if not ticker:
            continue

        rating = row.get("rating", "")
        avoid_flag = "回避" in rating or row.get("avoid", "").lower() in {"1", "true", "yes", "y"}
        if avoid_flag:
            avoid.append(ticker)

        tickers[ticker] = {
            "score": _float(row.get("score", "")),
            "evidence": row.get("evidence", ""),
            "rating": rating,
            "sector": row.get("sector", ""),
            "rank": _int(row.get("rank", "")),
            "business_purity": row.get("business_purity", ""),
            "risks": _split_values(row.get("risks", "")),
            "catalysts": _split_values(row.get("catalysts", "")),
            "avoid": avoid_flag,
        }

    return {"as_of": _as_of(html), "avoid": sorted(set(avoid)), "tickers": tickers}


def _label_value(text: str, labels: Iterable[str]) -> str:
    for label in labels:
        pattern = rf"{re.escape(label)}\s*[:：]\s*([^\n]+)"
        match = re.search(pattern, text)
        if match:
            return _clean(match.group(1))
    return ""


def parse_market_risk_html(html: str) -> Dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    text = soup.get_text("\n", strip=True)
    rules = []
    for row in _extract_tables(html):
        name = row.get("name", "")
        if not name:
            continue
        rules.append(
            {
                "name": name,
                "status": row.get("status", ""),
                "value": row.get("value", ""),
                "trigger": row.get("trigger", ""),
            }
        )

    return {
        "as_of": _as_of(html),
        "market_state": _label_value(text, ["市场状态", "Market State"]),
        "bubble_phase": _label_value(text, ["泡沫阶段", "Bubble Phase"]),
        "sector_overheats": _split_values(_label_value(text, ["过热板块", "Sector Overheats"])),
        "rules": rules,
    }


def parse_earnings_html(html: str) -> Dict[str, Any]:
    events: Dict[str, Dict[str, Any]] = {}
    for row in _extract_tables(html):
        ticker = _ticker(row.get("ticker", ""))
        if not ticker:
            continue
        events[ticker] = {
            "date": row.get("date", ""),
            "timing": row.get("timing", ""),
            "eps_estimate": row.get("eps_estimate", ""),
            "revenue_estimate": row.get("revenue_estimate", ""),
            "implied_move": _float(row.get("implied_move", "")),
        }
    return {"as_of": _as_of(html), "events": events}


def _write_json(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _merge_research(items: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    result = {"as_of": date.today().isoformat(), "avoid": [], "tickers": {}}
    for item in items:
        if item.get("as_of"):
            result["as_of"] = item["as_of"]
        result["avoid"].extend(item.get("avoid", []))
        result["tickers"].update(item.get("tickers", {}))
    result["avoid"] = sorted(set(result["avoid"]))
    return result


def _classify_html(path: Path) -> str:
    name = path.name.lower()
    if "earning" in name or "财报" in name:
        return "earnings"
    if any(token in name for token in ["market", "risk", "bubble", "泡沫"]):
        return "market"
    return "research"


def refresh_cache_from_html_dir(html_dir: str | Path, cache_dir: str | Path) -> Dict[str, Any]:
    html_path = Path(html_dir)
    output_path = Path(cache_dir)
    if not html_path.exists():
        raise FileNotFoundError(f"WSS HTML目录不存在: {html_path}")

    research_items = []
    market_payload: Optional[Dict[str, Any]] = None
    earnings_payload: Optional[Dict[str, Any]] = None

    for path in sorted(html_path.glob("*.html")):
        html = path.read_text(encoding="utf-8")
        kind = _classify_html(path)
        if kind == "earnings":
            earnings_payload = parse_earnings_html(html)
        elif kind == "market":
            market_payload = parse_market_risk_html(html)
        else:
            parsed = parse_research_html(html)
            if parsed.get("tickers"):
                research_items.append(parsed)

    research_payload = _merge_research(research_items) if research_items else None

    written = []
    if research_payload is not None:
        _write_json(output_path / "research.json", research_payload)
        written.append("research.json")
    if market_payload is not None:
        _write_json(output_path / "market_risk.json", market_payload)
        written.append("market_risk.json")
    if earnings_payload is not None:
        _write_json(output_path / "earnings.json", earnings_payload)
        written.append("earnings.json")

    return {
        "status": "ok",
        "cache_dir": str(output_path),
        "written": written,
        "research_count": len((research_payload or {}).get("tickers", {})),
        "market_rules_count": len((market_payload or {}).get("rules", [])),
        "earnings_count": len((earnings_payload or {}).get("events", {})),
    }


def refresh_cache_from_web(cache_dir: str | Path, cookie: Optional[str] = None) -> Dict[str, Any]:
    import requests

    cookie = cookie or os.environ.get("WSS_COOKIE", "")
    if not cookie:
        raise ValueError("refresh_source_required: 请提供 --wss-html-dir 或环境变量 WSS_COOKIE")

    from tempfile import TemporaryDirectory

    with TemporaryDirectory() as tmp:
        html_dir = Path(tmp)
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0", "Cookie": cookie})
        for filename, url in DEFAULT_WSS_URLS.items():
            response = session.get(urljoin("https://wall-street-skill.com/", url), timeout=20)
            response.raise_for_status()
            html = response.text
            if "auth=login" in response.url:
                raise PermissionError("wss_auth_required: 当前 WSS_COOKIE 未通过登录校验")
            (html_dir / filename).write_text(html, encoding="utf-8")
        return refresh_cache_from_html_dir(html_dir, cache_dir)
