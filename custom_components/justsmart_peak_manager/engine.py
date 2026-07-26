"""Clock-aligned 15-minute peak calculation independent from Home Assistant."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime

INTERVAL_SECONDS = 15 * 60


@dataclass(slots=True)
class PeakSnapshot:
    """Serializable engine state plus the latest derived values."""

    target_kw: float
    warning_margin_kw: float = 0.5
    protect_monthly_peak: bool = True
    interval_start: datetime | None = None
    energy_ws: float = 0.0
    last_timestamp: datetime | None = None
    last_import_w: float = 0.0
    monthly_peak_kw: float = 0.0
    monthly_peak_at: datetime | None = None
    month_key: str = ""
    data_quality: str = "complete"
    interval_end: datetime | None = None
    elapsed_seconds: float = 0.0
    seconds_remaining: float = INTERVAL_SECONDS
    current_import_kw: float = 0.0
    interval_average_kw: float = 0.0
    projected_kw: float = 0.0
    active_limit_kw: float = 0.0
    headroom_kw: float = 0.0
    recommended_reduction_kw: float = 0.0
    status: str = "normal"
    active_action: str = "Netzbezug im Zielbereich"


class PeakEngine:
    """Integrate import power into local, clock-aligned quarter-hour windows."""

    def __init__(
        self,
        target_kw: float,
        warning_margin_kw: float = 0.5,
        protect_monthly_peak: bool = True,
    ) -> None:
        if target_kw <= 0:
            raise ValueError("target_kw must be greater than zero")
        if warning_margin_kw < 0:
            raise ValueError("warning_margin_kw cannot be negative")
        self.state = PeakSnapshot(
            target_kw=float(target_kw),
            warning_margin_kw=float(warning_margin_kw),
            protect_monthly_peak=bool(protect_monthly_peak),
        )

    @classmethod
    def from_snapshot(cls, snapshot: PeakSnapshot) -> PeakEngine:
        engine = cls(snapshot.target_kw, snapshot.warning_margin_kw, snapshot.protect_monthly_peak)
        engine.state = replace(snapshot)
        return engine

    def set_target(self, target_kw: float) -> None:
        if target_kw <= 0:
            raise ValueError("target_kw must be greater than zero")
        self.state.target_kw = float(target_kw)

    def set_monthly_peak(self, peak_kw: float, occurred_at: datetime | None = None) -> None:
        self.state.monthly_peak_kw = max(0.0, float(peak_kw))
        self.state.monthly_peak_at = occurred_at
        if occurred_at is not None:
            self.state.month_key = self._month_key(occurred_at)

    def reset_monthly_peak(self, now: datetime) -> PeakSnapshot:
        self._require_aware(now)
        self.state.month_key = self._month_key(now)
        self.state.monthly_peak_kw = 0.0
        self.state.monthly_peak_at = None
        return self._reading(now)

    def update(self, power_w: float, now: datetime) -> PeakSnapshot:
        """Integrate the previous sample until ``now`` and accept a new power sample."""
        self._require_aware(now)
        new_import_w = self._import_w(power_w)
        state = self.state

        if state.last_timestamp is None or state.interval_start is None:
            state.interval_start = self._interval_start(now)
            state.last_timestamp = now
            state.last_import_w = new_import_w
            elapsed = self._seconds_between(state.interval_start, now)
            state.energy_ws = new_import_w * max(0.0, elapsed)
            state.month_key = self._month_key(now)
            state.data_quality = (
                "complete" if now.timestamp() == state.interval_start.timestamp() else "partial"
            )
            return self._reading(now)

        if now.timestamp() < state.last_timestamp.timestamp():
            raise ValueError("samples must be chronological")

        self._integrate_until(now)
        state.last_import_w = new_import_w
        return self._reading(now)

    def resume(self, power_w: float, now: datetime) -> PeakSnapshot:
        """Resume after downtime without assuming the stale sample persisted."""
        self._require_aware(now)
        current_start = self._interval_start(now)
        if (
            self.state.interval_start is None
            or self.state.interval_start.timestamp() != current_start.timestamp()
        ):
            self.state.interval_start = current_start
            self.state.energy_ws = 0.0
        if self.state.month_key != self._month_key(now):
            self.state.month_key = self._month_key(now)
            self.state.monthly_peak_kw = 0.0
            self.state.monthly_peak_at = None
        self.state.last_timestamp = now
        self.state.last_import_w = self._import_w(power_w)
        self.state.data_quality = "partial"
        return self._reading(now)

    def snapshot(self) -> PeakSnapshot:
        return replace(self.state)

    def _integrate_until(self, now: datetime) -> None:
        state = self.state
        assert state.last_timestamp is not None
        assert state.interval_start is not None

        while state.last_timestamp.timestamp() < now.timestamp():
            interval_end = self._add_seconds(state.interval_start, INTERVAL_SECONDS)
            segment_end = min(now, interval_end, key=lambda value: value.timestamp())
            duration = self._seconds_between(state.last_timestamp, segment_end)
            state.energy_ws += state.last_import_w * max(0.0, duration)
            state.last_timestamp = segment_end

            if segment_end.timestamp() == interval_end.timestamp():
                finished_kw = state.energy_ws / INTERVAL_SECONDS / 1000.0
                finished_month = self._month_key(state.interval_start)
                if state.month_key != finished_month:
                    state.month_key = finished_month
                    state.monthly_peak_kw = 0.0
                    state.monthly_peak_at = None
                if finished_kw > state.monthly_peak_kw:
                    state.monthly_peak_kw = finished_kw
                    state.monthly_peak_at = state.interval_start

                state.interval_start = interval_end
                state.energy_ws = 0.0
                state.data_quality = "complete"
                next_month = self._month_key(state.interval_start)
                if next_month != state.month_key:
                    state.month_key = next_month
                    state.monthly_peak_kw = 0.0
                    state.monthly_peak_at = None

    def _reading(self, now: datetime) -> PeakSnapshot:
        state = self.state
        assert state.interval_start is not None
        interval_end = self._add_seconds(state.interval_start, INTERVAL_SECONDS)
        elapsed = min(
            INTERVAL_SECONDS,
            max(0.0, self._seconds_between(state.interval_start, now)),
        )
        remaining = max(0.0, INTERVAL_SECONDS - elapsed)
        current_kw = state.last_import_w / 1000.0
        average_kw = state.energy_ws / elapsed / 1000.0 if elapsed else current_kw
        projected_ws = state.energy_ws + state.last_import_w * remaining
        projected_kw = projected_ws / INTERVAL_SECONDS / 1000.0
        active_limit = state.target_kw
        if state.protect_monthly_peak and state.monthly_peak_kw > active_limit:
            active_limit = state.monthly_peak_kw
        headroom = active_limit - projected_kw
        reduction = (
            max(0.0, -headroom * INTERVAL_SECONDS / remaining)
            if remaining > 0
            else 0.0
        )
        if projected_kw > active_limit:
            status = "limiting"
        elif projected_kw >= max(0.0, active_limit - state.warning_margin_kw):
            status = "warning"
        else:
            status = "normal"

        derived = replace(
            state,
            interval_end=interval_end,
            elapsed_seconds=elapsed,
            seconds_remaining=remaining,
            current_import_kw=current_kw,
            interval_average_kw=average_kw,
            projected_kw=projected_kw,
            active_limit_kw=active_limit,
            headroom_kw=headroom,
            recommended_reduction_kw=reduction,
            status=status,
        )
        return derived

    @staticmethod
    def _interval_start(value: datetime) -> datetime:
        timestamp = value.timestamp()
        return datetime.fromtimestamp(
            timestamp - (timestamp % INTERVAL_SECONDS), value.tzinfo
        )

    @staticmethod
    def _add_seconds(value: datetime, seconds: float) -> datetime:
        return datetime.fromtimestamp(value.timestamp() + seconds, value.tzinfo)

    @staticmethod
    def _seconds_between(start: datetime, end: datetime) -> float:
        return end.timestamp() - start.timestamp()

    @staticmethod
    def _month_key(value: datetime) -> str:
        return value.strftime("%Y-%m")

    @staticmethod
    def _import_w(power_w: float) -> float:
        value = float(power_w)
        if value != value or value in (float("inf"), float("-inf")):
            raise ValueError("power_w must be finite")
        return max(0.0, value)

    @staticmethod
    def _require_aware(value: datetime) -> None:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must be timezone-aware")
