"""Explainable, advisory football match analysis based only on supplied data."""
from __future__ import annotations

from dataclasses import dataclass
import csv
from io import TextIOWrapper
from math import exp, factorial, isfinite
import re
from typing import Any
from urllib.parse import urlparse
from urllib.request import Request, urlopen

SUPPORTED_BOOKMAKERS = frozenset({"unknown", "snai", "goldbet", "better", "bet365", "sisal", "eurobet"})
BOOKMAKER_DOMAINS = ("snai.it", "goldbet.it", "better.it", "bet365.it", "sisal.it", "eurobet.it")
_ODD_RE = re.compile(r"(?<![\d.,])([1-9]\d?(?:[.,]\d{1,2}))(?![\d.,])")
_MAX_MATCHES = 100
_FOOTBALL_DATA_HOST = "www.football-data.co.uk"
_MAX_DOWNLOAD_BYTES = 8 * 1024 * 1024


@dataclass(frozen=True)
class Quote:
    bookmaker: str
    market: str
    selection: str
    decimal: float


def collect_historical_results(home_team: str, away_team: str, league: str = "I1", seasons: tuple[str, ...] = ("2526",), *, opener=urlopen) -> dict[str, Any]:
    """Collect bounded historical CSV rows from Football-Data.

    The caller chooses league/seasons; failures are returned as warnings rather
    than turning a match analysis into an unbounded network dependency.
    """
    home_name, away_name = str(home_team or "").strip(), str(away_team or "").strip()
    if not home_name or not away_name:
        return {"home_history": [], "away_history": [], "warnings": ["Squadre mancanti per la raccolta storica."]}
    home_rows, away_rows, sources, warnings = [], [], [], []
    for season in list(seasons or ())[:5]:
        url = f"https://{_FOOTBALL_DATA_HOST}/mmz4281/{str(season).strip()}/{str(league).strip().upper()}.csv"
        if urlparse(url).hostname != _FOOTBALL_DATA_HOST:
            warnings.append("Fonte storica non autorizzata.")
            continue
        try:
            request = Request(url, headers={"User-Agent": "JARVIS-football-analysis/1.0"})
            with opener(request, timeout=15) as response:
                raw = response.read(_MAX_DOWNLOAD_BYTES + 1)
            if len(raw) > _MAX_DOWNLOAD_BYTES:
                raise ValueError("dataset storico oltre il limite consentito")
            reader = csv.DictReader(TextIOWrapper(__import__("io").BytesIO(raw), encoding="utf-8-sig", errors="replace"))
            for row in reader:
                if not isinstance(row, dict):
                    continue
                home, away = str(row.get("HomeTeam") or "").casefold(), str(row.get("AwayTeam") or "").casefold()
                hg, ag = _number(row.get("FTHG"), 0, 30), _number(row.get("FTAG"), 0, 30)
                if hg is None or ag is None:
                    continue
                if home == home_name.casefold():
                    home_rows.append({"home_goals": hg, "away_goals": ag, "result": str(row.get("FTR") or "").casefold(), "date": row.get("Date"), "opponent": row.get("AwayTeam"), "shots": row.get("HS"), "shots_on_target": row.get("HST")})
                if away == away_name.casefold():
                    away_rows.append({"away_goals": ag, "home_goals": hg, "result": str(row.get("FTR") or "").casefold(), "date": row.get("Date"), "opponent": row.get("HomeTeam"), "shots": row.get("AS"), "shots_on_target": row.get("AST")})
            sources.append(url)
        except (OSError, ValueError, UnicodeError, csv.Error) as exc:
            warnings.append(f"Fonte storica non disponibile per {season}: {type(exc).__name__}.")
    return {"home_history": home_rows[-_MAX_MATCHES:], "away_history": away_rows[-_MAX_MATCHES:], "sources": sources, "warnings": warnings}


def _number(value: Any, minimum: float | None = None, maximum: float | None = None) -> float | None:
    try:
        number = float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None
    if not isfinite(number) or (minimum is not None and number < minimum) or (maximum is not None and number > maximum):
        return None
    return number


def _decimal(value: Any) -> float | None:
    return _number(value, minimum=1.0 + 1e-9)


def normalize_quotes(raw: list[dict[str, Any]] | None) -> list[Quote]:
    normalized = []
    for row in list(raw or [])[:500]:
        if not isinstance(row, dict):
            continue
        odd = _decimal(row.get("decimal", row.get("odds")))
        if odd is not None and str(row.get("selection") or "").strip():
            normalized.append(Quote(str(row.get("bookmaker") or "unknown").strip().casefold(), str(row.get("market") or "1x2").strip().casefold(), str(row["selection"]).strip().casefold(), odd))
    return normalized


def extract_visible_quotes(text: str, bookmaker: str = "unknown", limit: int = 150) -> list[dict[str, Any]]:
    try:
        limit = max(1, min(int(limit), 500))
    except (TypeError, ValueError, OverflowError):
        limit = 150
    rows = []
    for line in str(text or "").splitlines():
        match = _ODD_RE.search(line)
        if match:
            selection = line[:match.start()].strip(" -:|\t")
            if selection:
                rows.append({"bookmaker": bookmaker, "market": "1x2", "selection": selection, "decimal": float(match.group(1).replace(",", "."))})
        if len(rows) >= limit:
            break
    return rows


def _market_summary(quotes: list[Quote], market: str) -> dict[str, Any]:
    selected = [quote for quote in quotes if quote.market == market]
    best = {}
    for quote in selected:
        if quote.selection not in best or quote.decimal > best[quote.selection]["decimal"]:
            best[quote.selection] = {"bookmaker": quote.bookmaker, "decimal": quote.decimal}
    return {"market": market, "quotes": [quote.__dict__ for quote in selected], "best": best}


def _matches(raw: Any) -> list[dict[str, Any]]:
    return [row for row in list(raw or [])[:_MAX_MATCHES] if isinstance(row, dict)]


def _goals(match: dict[str, Any], side: str) -> tuple[float, float] | None:
    if side == "home":
        scored, conceded = match.get("home_goals", match.get("goals_for")), match.get("away_goals", match.get("goals_against"))
    else:
        scored, conceded = match.get("away_goals", match.get("goals_for")), match.get("home_goals", match.get("goals_against"))
    scored, conceded = _number(scored, 0, 30), _number(conceded, 0, 30)
    return None if scored is None or conceded is None else (scored, conceded)


def _team_profile(matches: list[dict[str, Any]], venue: str) -> dict[str, Any]:
    values = []
    for index, match in enumerate(matches):
        goals = _goals(match, venue)
        if goals is None:
            continue
        scored, conceded = goals
        result = str(match.get("result") or "").casefold()
        result = result if result in {"w", "d", "l", "win", "draw", "loss"} else ("w" if scored > conceded else "d" if scored == conceded else "l")
        values.append((scored, conceded, result, 1 / (1 + index * 0.12)))
    weight = sum(row[3] for row in values)
    if not weight:
        return {"matches": 0, "goals_for": None, "goals_against": None, "points_per_match": None, "clean_sheet_rate": None}
    return {"matches": len(values), "goals_for": round(sum(r[0] * r[3] for r in values) / weight, 3), "goals_against": round(sum(r[1] * r[3] for r in values) / weight, 3), "points_per_match": round(sum((3 if r[2] in {"w", "win"} else 1 if r[2] in {"d", "draw"} else 0) * r[3] for r in values) / weight, 3), "clean_sheet_rate": round(sum(r[1] == 0 for r in values) / len(values), 3)}


def _metric(profile: Any, key: str, default: float | None = None) -> float | None:
    return _number(profile.get(key), 0) if isinstance(profile, dict) else default


def _expected_goals(snapshot: dict[str, Any], home: dict[str, Any], away: dict[str, Any]) -> tuple[float, float, list[dict[str, Any]]]:
    stats = snapshot.get("team_stats") if isinstance(snapshot.get("team_stats"), dict) else {}
    hs, aws = stats.get("home", stats), stats.get("away", {})
    ha = _metric(hs, "xg_for") or _metric(hs, "goals_for") or home["goals_for"]
    aa = _metric(aws, "xg_for") or _metric(aws, "goals_for") or away["goals_for"]
    hd = _metric(hs, "xg_against") or _metric(hs, "goals_against") or home["goals_against"]
    ad = _metric(aws, "xg_against") or _metric(aws, "goals_against") or away["goals_against"]
    hx = 1.35 + ((ha or 1.35) - 1.35) * .45 + ((ad or 1.35) - 1.35) * .25 + .15
    ax = 1.10 + ((aa or 1.10) - 1.10) * .45 + ((hd or 1.35) - 1.35) * .25
    factors = []
    if home["matches"]: hx += (home["points_per_match"] - 1.5) * .08; factors.append({"factor": "forma casa", "value": home["points_per_match"], "weight": .25})
    if away["matches"]: ax += (away["points_per_match"] - 1.5) * .08; factors.append({"factor": "forma trasferta", "value": away["points_per_match"], "weight": .25})
    for label, profile in (("casa", hs), ("trasferta", aws)):
        rest = _metric(profile, "rest_days")
        if rest is not None and rest < 4:
            if label == "casa": hx -= .08
            else: ax -= .08
            factors.append({"factor": f"riposo {label}", "value": rest, "weight": .10})
    return max(.15, min(4.5, hx)), max(.15, min(4.5, ax)), factors


def _probabilities(home_xg: float, away_xg: float) -> dict[str, float]:
    home = [exp(-home_xg) * home_xg**i / factorial(i) for i in range(9)]
    away = [exp(-away_xg) * away_xg**i / factorial(i) for i in range(9)]
    total = 0.0; result = {"home": 0.0, "draw": 0.0, "away": 0.0, "over_2_5": 0.0, "btts": 0.0}
    for h, ph in enumerate(home):
        for a, pa in enumerate(away):
            p = ph * pa; total += p
            result["home"] += p * (h > a); result["draw"] += p * (h == a); result["away"] += p * (h < a); result["over_2_5"] += p * (h + a >= 3); result["btts"] += p * (h > 0 and a > 0)
    return {key: value / total for key, value in result.items()}


def analyze_match(snapshot: dict[str, Any]) -> dict[str, Any]:
    snapshot = dict(snapshot or {})
    collected = {}
    if snapshot.get("collect_historical"):
        collected = collect_historical_results(snapshot.get("home"), snapshot.get("away"), snapshot.get("league", "I1"), tuple(snapshot.get("seasons") or ("2526",)))
        snapshot.setdefault("home_history", collected.get("home_history", []))
        snapshot.setdefault("away_history", collected.get("away_history", []))
    quotes = normalize_quotes(snapshot.get("quotes"))
    history = snapshot.get("history") if isinstance(snapshot.get("history"), dict) else {}
    home_history = _matches(snapshot.get("home_history", history.get("home", [])))
    away_history = _matches(snapshot.get("away_history", history.get("away", [])))
    h2h = _matches(snapshot.get("head_to_head", snapshot.get("h2h", [])))
    home, away = _team_profile(home_history, "home"), _team_profile(away_history, "away")
    home_xg, away_xg, factors = _expected_goals(snapshot, home, away)
    h2h_home, h2h_away = _team_profile(h2h, "home"), _team_profile(h2h, "away")
    if h2h_home["matches"] and h2h_away["matches"]:
        home_xg = max(.15, min(4.5, home_xg + (h2h_home["points_per_match"] - 1.5) * .04))
        away_xg = max(.15, min(4.5, away_xg + (h2h_away["points_per_match"] - 1.5) * .04))
        factors.append({"factor": "scontri diretti", "value": {"casa": h2h_home["points_per_match"], "trasferta": h2h_away["points_per_match"]}, "weight": .10})
    probabilities = _probabilities(home_xg, away_xg)
    warnings = []
    warnings.extend(collected.get("warnings", []))
    if not quotes: warnings.append("Nessuna quota strutturata disponibile.")
    if not home["matches"] or not away["matches"]: warnings.append("Forma storica incompleta: servono partite precedenti per entrambe le squadre.")
    if not h2h: warnings.append("Scontri diretti non disponibili.")
    stats = dict(snapshot.get("stats") or {}); stats.update({"home_form": home, "away_form": away, "head_to_head_matches": len(h2h), "expected_goals": {"home": round(home_xg, 3), "away": round(away_xg, 3)}})
    confidence = min(.95, .25 + min(home["matches"], 10) * .025 + min(away["matches"], 10) * .025 + (.15 if snapshot.get("team_stats") else 0) + (.10 if h2h else 0))
    result = {"home": str(snapshot.get("home") or ""), "away": str(snapshot.get("away") or ""), "stats": stats, "probabilities": {key: round(value, 4) for key, value in probabilities.items()}, "fair_odds": {key: round(1 / value, 2) for key, value in probabilities.items() if value}, "expected_goals": {"home": round(home_xg, 3), "away": round(away_xg, 3)}, "factors": factors, "confidence": round(confidence, 3), "markets": [_market_summary(quotes, market) for market in sorted({q.market for q in quotes})], "warnings": warnings, "advisory_only": True, "execution": {"bet_placement": False}}
    if collected.get("sources"):
        result["sources"] = collected["sources"]
    if snapshot.get("weather"): result["context"] = {"weather": dict(snapshot["weather"])}
    return result


def format_analysis(result: dict[str, Any]) -> str:
    labels = {"home": "casa", "draw": "pareggio", "away": "trasferta"}
    probabilities = result.get("probabilities") or {}
    ordered = sorted(((labels[key], value) for key, value in probabilities.items() if key in labels), key=lambda row: row[1], reverse=True)
    summary = ", ".join(f"{label} {value:.0%}" for label, value in ordered)
    goals = result.get("expected_goals", {})
    return f"Analisi advisory {result.get('home') or 'Casa'}-{result.get('away') or 'Trasferta'}: {summary}. Gol attesi {goals.get('home', 0):.2f}-{goals.get('away', 0):.2f}. Confidenza {result.get('confidence', 0):.0%}. {' '.join(result.get('warnings', []))}".strip()
