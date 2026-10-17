from __future__ import annotations

from dataclasses import asdict
from typing import Any
import numpy as np
import pandas as pd
from naked_k_config import DualMAConfig
from naked_k_zones import detect_price_zones, validate_ohlcv

MIN_HISTORY = 120
RULE_VERSION = 'bige-dual-ma-v1'
MA_PERIODS = (20, 60, 120)
SOURCE_URL = 'https://www.youtube.com/watch?v=vdCdg4MdwBs'


def _validated(frame: pd.DataFrame) -> pd.DataFrame:
    return validate_ohlcv(frame)


def _smooth(values: pd.Series, period: int, alpha: float) -> pd.Series:
    source = values.to_numpy(dtype=float)
    output = np.full(len(source), np.nan)
    if len(values) >= period:
        output[period - 1] = source[:period].mean()
        for i in range(period, len(source)):
            output[i] = output[i - 1] + alpha * (source[i] - output[i - 1])
    return pd.Series(output, index=values.index)


def _true_range(frame: pd.DataFrame) -> pd.Series:
    previous = frame.Close.shift()
    return pd.concat([frame.High - frame.Low, (frame.High - previous).abs(), (frame.Low - previous).abs()], axis=1).max(axis=1)


def _adx(frame: pd.DataFrame, period: int = 14) -> pd.Series:
    up, down = frame.High.diff(), -frame.Low.diff()
    plus = pd.Series(np.where((up > down) & (up > 0), up, 0.0), index=frame.index)
    minus = pd.Series(np.where((down > up) & (down > 0), down, 0.0), index=frame.index)
    atr = _smooth(_true_range(frame), period, 1 / period)
    plus_di = (100 * _smooth(plus, period, 1 / period) / atr).where(atr != 0, 0.0)
    minus_di = (100 * _smooth(minus, period, 1 / period) / atr).where(atr != 0, 0.0)
    denominator = plus_di + minus_di
    dx = (100 * (plus_di - minus_di).abs() / denominator).where(denominator != 0, 0.0)
    adx = _smooth(dx.iloc[period - 1:], period, 1 / period)
    return adx.reindex(frame.index)


def indicator_frame(frame: pd.DataFrame) -> pd.DataFrame:
    result = _validated(frame)
    for period in (20, 50, 60, 120, 200):
        result[f"ema{period}"] = _smooth(result.Close, period, 2 / (period + 1))
    for period in MA_PERIODS:
        result[f'ma{period}'] = result.Close.rolling(period).mean()
    result["atr"] = _smooth(_true_range(result), 14, 1 / 14)
    result["atr_pct"] = result.atr / result.Close * 100
    result["adx"] = _adx(result)
    result["channel_high"] = result.High.shift().rolling(20).max()
    result["channel_low"] = result.Low.shift().rolling(20).min()
    baseline = result.Volume.shift().rolling(20).mean()
    result["relative_volume"] = (result.Volume / baseline).where((result.Volume > 0) & (baseline > 0))
    result["ema50_slope"] = result.ema50 - result.ema50.shift(5)
    return result


def _number(value: Any) -> float | None:
    return float(value) if pd.notna(value) and np.isfinite(value) else None


def _bands(row) -> list[tuple[float, float]]:
    return [(min(getattr(row, f'ma{p}'), getattr(row, f'ema{p}')),
             max(getattr(row, f'ma{p}'), getattr(row, f'ema{p}'))) for p in MA_PERIODS]


def _ordered(bands: list[tuple[float, float]], side: str) -> bool:
    if side == 'long':
        return bands[0][0] > bands[1][1] and bands[1][0] > bands[2][1]
    return bands[0][1] < bands[1][0] and bands[1][1] < bands[2][0]


def _setups(data: pd.DataFrame, config: DualMAConfig) -> dict[str, Any]:
    """Replay closed bars, freezing the cluster before its first breakout bar."""
    cluster, pending, confirmed, event = None, None, None, None
    history, run, episode, registered = [], 0, None, None
    detached = consumed = False
    state = 'waiting_cluster'
    for i, row in enumerate(data.itertuples()):
        event = None
        if i + 1 < MIN_HISTORY:
            continue
        bands = _bands(row)
        lower, upper = min(x[0] for x in bands), max(x[1] for x in bands)
        dense = (upper / lower - 1) * 100 <= config.cluster_width_pct
        if dense:
            if run == 0:
                episode = i
            run += 1
        else:
            run = 0
        if run >= config.cluster_min_bars and episode != registered:
            if cluster:
                history.append(dict(cluster))
            registered = episode
            cluster = {'start': pd.Timestamp(data.index[episode]).isoformat(),
                       'end': pd.Timestamp(row.Index).isoformat(), 'lower': lower, 'upper': upper,
                       'last_index': i}
            pending = confirmed = None
            detached = consumed = False
            state = 'cluster_ready'
            continue
        if cluster is None:
            continue
        if confirmed is None:
            if i - cluster['last_index'] > config.setup_max_bars:
                state = 'expired'
                continue
            side = 'long' if row.Close > cluster['upper'] else 'short' if row.Close < cluster['lower'] else None
            if side:
                count = pending['count'] + 1 if pending and pending['side'] == side else 1
                pending = {'side': side, 'count': count}
                state = 'breakout_pending'
                if count >= config.confirmation_bars:
                    confirmed = {'side': side, 'index': i}
                    event = {'kind': 'cluster_breakout', 'side': side}
                    state = 'breakout_confirmed'
                    detached = row.Low > bands[0][1] if side == 'long' else row.High < bands[0][0]
            else:
                pending = None
                state = 'cluster_ready'
                if dense:
                    cluster.update(lower=lower, upper=upper, end=pd.Timestamp(row.Index).isoformat(), last_index=i)
        else:
            side = confirmed['side']
            invalid = row.Close < cluster['lower'] if side == 'long' else row.Close > cluster['upper']
            if invalid:
                consumed, state = True, 'invalidated'
            elif i - confirmed['index'] > config.setup_max_bars:
                consumed, state = True, 'expired'
            elif not consumed:
                touch = row.Low <= bands[0][1] if side == 'long' else row.High >= bands[0][0]
                held = row.Close > bands[0][1] if side == 'long' else row.Close < bands[0][0]
                if detached and touch:
                    consumed = True
                    state = 'pullback_consumed'
                    if held and _ordered(bands, side):
                        event = {'kind': 'first_pullback_20', 'side': side}
                        state = 'pullback_confirmed'
                else:
                    state = 'waiting_first_pullback'
                    detached = detached or (row.Low > bands[0][1] if side == 'long' else row.High < bands[0][0])
            elif state == 'pullback_confirmed':
                state = 'pullback_consumed'
        if event:
            band = (cluster['lower'], cluster['upper']) if event['kind'] == 'cluster_breakout' else bands[0]
            stop = band[0] * (1 - config.stop_buffer_pct / 100) if event['side'] == 'long' else band[1] * (1 + config.stop_buffer_pct / 100)
            event.update(confirmed_at=pd.Timestamp(row.Index).isoformat(), stop_loss=stop,
                         entry_floor=band[1] if event['side'] == 'long' else None,
                         cluster_start=cluster['start'])
    clean = lambda x: {k: v for k, v in x.items() if k != 'last_index'}
    return {'setup': event, 'setup_state': state, 'cluster': clean(cluster) if cluster else None,
            'historical_clusters': [clean(x) for x in history]}


def _fibonacci(data: pd.DataFrame, config: DualMAConfig, ticker: str | None) -> dict[str, Any]:
    anchor = config.fibonacci_anchors.get(ticker or '')
    if not anchor:
        return {'status': 'missing_explicit_anchors', 'levels': {}}
    dates = list(data.index.strftime('%Y-%m-%d'))
    if anchor['high_date'] not in dates or anchor['low_date'] not in dates:
        return {'status': 'anchors_outside_available_history', 'levels': {}}
    high_i, low_i = dates.index(anchor['high_date']), dates.index(anchor['low_date'])
    high, low = float(data.High.iloc[high_i]), float(data.Low.iloc[low_i])
    if high <= low or high < data.High.iloc[:high_i + 1].max():
        return {'status': 'invalid_anchor_prices', 'levels': {}}
    levels = {str(r): low + r * (high - low) for r in (1.618, 2.618, 3.618, 4.236)}
    return {'status': 'ready' if data.Close.iloc[-1] > high else 'awaiting_anchor_high_break',
            'high_date': anchor['high_date'], 'low_date': anchor['low_date'], 'high': high, 'low': low,
            'levels': levels, 'scope': 'explicit_available_history_anchors_not_verified_all_time_high'}


def analyze_trend(frame: pd.DataFrame, config: DualMAConfig | None = None, *, ticker: str | None = None) -> dict[str, Any]:
    config = config or DualMAConfig()
    data = indicator_frame(frame)
    if data.empty:
        raise ValueError('OHLCV must contain at least one row')
    row, ready = data.iloc[-1], len(data) >= MIN_HISTORY
    close, adx = _number(row.Close), _number(row.adx)
    bands = _bands(row)
    lower, upper = min(x[0] for x in bands), max(x[1] for x in bands)
    width = (upper / lower - 1) * 100 if ready else None
    direction = ('up' if close > upper else 'down' if close < lower else 'transition') if ready else 'unknown'
    ma_state = ('compression' if width <= config.cluster_width_pct else
                'expanding_up' if _ordered(bands, 'long') else 'expanding_down' if _ordered(bands, 'short') else 'mixed') if ready else 'insufficient'
    context = _setups(data, config)
    setup = context['setup']
    stop = setup['stop_loss'] if setup and setup['side'] == 'long' else None
    risk = close - stop if stop is not None and 0 < stop < close else None
    target_clusters = sorted((c for c in context['historical_clusters'] if c['lower'] > close), key=lambda c: c['lower'])
    fibonacci = _fibonacci(data, config, ticker)
    target = None
    if config.exit_method == 'fixed_r' and risk is not None:
        target = close + risk * config.take_profit_r
    elif config.exit_method == 'previous_cluster' and target_clusters:
        target = target_clusters[0]['lower']
    elif config.exit_method == 'fibonacci' and fibonacci['status'] == 'ready':
        target = fibonacci['levels'][str(config.fibonacci_ratio)]
    rr = (target - close) / risk if risk is not None and target is not None else None
    candidate = bool(ready and direction == 'up' and setup and setup['side'] == 'long' and risk is not None
                     and rr is not None and rr + 1e-9 >= config.min_reward_risk)
    reasons = [f'trend_{direction}', setup['kind'] if setup else 'no_new_setup']
    if setup and setup['side'] == 'short':
        reasons.append('long_only_defensive')
    if setup and setup['side'] == 'long' and direction != 'up':
        reasons.append('price_not_above_six_lines')
    if setup and setup['side'] == 'long' and target is None:
        reasons.append('target_unavailable')
    elif setup and setup['side'] == 'long' and (rr is None or rr + 1e-9 < config.min_reward_risk):
        reasons.append('insufficient_reward_risk')
    zones = detect_price_zones(frame, close=close)
    keys = [f'{kind}{p}' for p in MA_PERIODS for kind in ('ma', 'ema')]
    keys += ['ema50', 'ema200', 'atr', 'atr_pct', 'adx', 'channel_high', 'channel_low', 'relative_volume', 'ema50_slope']
    return {'status': 'ready' if ready else 'insufficient_history', 'direction': direction,
            'strength': 'unknown' if adx is None else 'strong' if adx >= 25 else 'developing' if adx >= 20 else 'weak',
            'history_mode': 'full' if ready else 'insufficient', 'daily_rows': len(data), 'rule_version': RULE_VERSION,
            'direction_basis': 'ma_ema_20_60_120' if ready else 'unavailable',
            'as_of': pd.Timestamp(data.index[-1]).isoformat(), 'close': close,
            'indicators': {key: _number(row[key]) for key in keys}, 'ma_state': ma_state, 'ma_width_pct': width,
            **context, 'zones': zones, 'breakout': bool(setup and setup['kind'] == 'cluster_breakout'),
            'entry_candidate': candidate, 'exit_signal': False,
            'entry_reference': close, 'entry_floor': setup['entry_floor'] if setup else None,
            'stop_loss': stop, 'max_entry': close + config.max_entry_gap_r * risk if risk is not None else None,
            'resistance': target_clusters[0]['lower'] if target_clusters else None,
            'target_price': target, 'reward_to_risk': rr, 'fibonacci': fibonacci,
            'exit_plan': {'method': config.exit_method, 'target_r': config.take_profit_r,
                          'target_price': target, 'min_reward_risk': config.min_reward_risk},
            'strategy': {'source_url': SOURCE_URL, 'implementation': 'documented_engineering_adaptation',
                         'parameters': asdict(config)}, 'reasons': reasons, 'validation_status': 'UNVALIDATED'}


def evaluate_entry(signal: dict[str, Any], open_price: float) -> dict[str, Any]:
    entry, stop, resistance = _number(open_price), _number(signal.get("stop_loss")), _number(signal.get("resistance"))
    result = {"eligible": False, "reason": "not_a_candidate", "entry": entry, "stop": stop,
              "risk_per_share": None, "resistance": resistance, "reward_to_risk": None, "target": None}
    if entry is None or entry <= 0:
        result["reason"] = "invalid_open"
    elif not signal.get("entry_candidate"):
        pass
    elif entry > signal.get("max_entry", -np.inf):
        result["reason"] = "open_above_max_entry"
    elif stop is None or entry <= stop:
        result["reason"] = "invalid_stop"
    elif signal.get('entry_floor') is not None and entry <= signal['entry_floor']:
        result['reason'] = 'open_back_inside_setup'
    else:
        risk = entry - stop
        plan = signal.get('exit_plan')
        target = (entry + risk * plan['target_r'] if plan['method'] == 'fixed_r' else plan['target_price']) if plan else resistance
        reward = target - entry if target is not None else None
        ratio = reward / risk if reward is not None else None
        result.update(risk_per_share=risk, reward_to_risk=ratio, target=target)
        if plan and (ratio is None or ratio + 1e-9 < plan['min_reward_risk']):
            result['reason'] = 'insufficient_reward_risk'
        elif not plan and resistance is not None and (reward <= 0 or ratio < 1):
            result['reason'] = 'insufficient_resistance_room'
        else:
            result.update(eligible=True, reason="eligible")
    return result


def protective_stop(signal: dict[str, Any], entry_setup: str | None, previous_stop: float | None) -> float | None:
    """Keep the original stop family: cluster fixed, first-pullback MA20 trailing."""
    if entry_setup != 'first_pullback_20' or previous_stop is None or signal.get('status') != 'ready':
        return previous_stop
    ind = signal['indicators']
    buffer = signal['strategy']['parameters']['stop_buffer_pct'] / 100
    return max(previous_stop, min(ind['ma20'], ind['ema20']) * (1 - buffer))
