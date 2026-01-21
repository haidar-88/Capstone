"""
Protocol Metrics and Observability (A6).

Provides structured metrics collection for MVCCP protocol behavior,
replacing scattered print statements with organized per-node metrics.
"""

from dataclasses import dataclass, field
from typing import Dict, List
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class NodeMetrics:
    """
    Per-node protocol metrics for observability and analysis.
    
    Tracks message counts, state transitions, session outcomes, and timing.
    All metrics are cumulative counters or running averages.
    """
    
    # Message counters by type
    messages_sent: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    messages_received: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    messages_forwarded: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    messages_dropped: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # State transition counters
    consumer_state_transitions: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    ph_state_transitions: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    rreh_state_transitions: Dict[str, int] = field(default_factory=lambda: defaultdict(int))
    
    # Session outcomes
    sessions_successful: int = 0
    sessions_failed: int = 0
    sessions_timeout: int = 0
    
    # Retry and backoff metrics
    total_retries: int = 0
    total_blacklist_events: int = 0
    backoff_durations: List[float] = field(default_factory=list)
    
    # Provider selection metrics
    rreh_selections: int = 0
    platoon_selections: int = 0
    detour_costs: List[float] = field(default_factory=list)
    urgency_ratios: List[float] = field(default_factory=list)  # P5
    queue_penalties: List[float] = field(default_factory=list)  # P7
    
    # Timing metrics
    session_durations: List[float] = field(default_factory=list)
    
    # MPR selections (Layer A)
    mpr_selections: int = 0
    mpr_forwards: int = 0
    
    def increment(self, category: str, key: str, count: int = 1):
        """
        Increment a counter in a specific category.
        
        Args:
            category: One of 'sent', 'received', 'forwarded', 'dropped'
            key: Counter name (e.g., message type, state name)
            count: Amount to increment (default 1)
        """
        if category == 'sent':
            self.messages_sent[key] += count
        elif category == 'received':
            self.messages_received[key] += count
        elif category == 'forwarded':
            self.messages_forwarded[key] += count
        elif category == 'dropped':
            self.messages_dropped[key] += count
        elif category == 'consumer_state':
            self.consumer_state_transitions[key] += count
        elif category == 'ph_state':
            self.ph_state_transitions[key] += count
        elif category == 'rreh_state':
            self.rreh_state_transitions[key] += count
    
    def record_timing(self, category: str, value: float):
        """
        Record a timing value for later analysis.
        
        Args:
            category: One of 'backoff', 'session', 'detour', 'urgency', 'queue_penalty'
            value: Timing value in seconds or metric value
        """
        if category == 'backoff':
            self.backoff_durations.append(value)
        elif category == 'session':
            self.session_durations.append(value)
        elif category == 'detour':
            self.detour_costs.append(value)
        elif category == 'urgency':
            self.urgency_ratios.append(value)
        elif category == 'queue_penalty':
            self.queue_penalties.append(value)
    
    def log_event(self, event_type: str, details: str = "", level: str = "info"):
        """
        Log a protocol event with structured logging.
        
        Args:
            event_type: Type of event (e.g., 'session_start', 'retry', 'blacklist')
            details: Additional details about the event
            level: Log level ('debug', 'info', 'warning', 'error')
        """
        log_func = getattr(logger, level, logger.info)
        if details:
            log_func(f"[{event_type}] {details}")
        else:
            log_func(f"[{event_type}]")
    
    def get_summary(self) -> Dict:
        """
        Get a summary of all metrics for analysis.
        
        Returns:
            Dictionary with metric summaries
        """
        return {
            'messages': {
                'sent': dict(self.messages_sent),
                'received': dict(self.messages_received),
                'forwarded': dict(self.messages_forwarded),
                'dropped': dict(self.messages_dropped),
                'total_sent': sum(self.messages_sent.values()),
                'total_received': sum(self.messages_received.values()),
                'total_forwarded': sum(self.messages_forwarded.values()),
                'total_dropped': sum(self.messages_dropped.values()),
            },
            'state_transitions': {
                'consumer': dict(self.consumer_state_transitions),
                'platoon_head': dict(self.ph_state_transitions),
                'rreh': dict(self.rreh_state_transitions),
            },
            'sessions': {
                'successful': self.sessions_successful,
                'failed': self.sessions_failed,
                'timeout': self.sessions_timeout,
                'total': self.sessions_successful + self.sessions_failed + self.sessions_timeout,
                'avg_duration': sum(self.session_durations) / len(self.session_durations) if self.session_durations else 0.0,
            },
            'retries': {
                'total_retries': self.total_retries,
                'total_blacklist_events': self.total_blacklist_events,
                'avg_backoff': sum(self.backoff_durations) / len(self.backoff_durations) if self.backoff_durations else 0.0,
            },
            'provider_selection': {
                'rreh_selections': self.rreh_selections,
                'platoon_selections': self.platoon_selections,
                'avg_detour_cost': sum(self.detour_costs) / len(self.detour_costs) if self.detour_costs else 0.0,
                'avg_urgency_ratio': sum(self.urgency_ratios) / len(self.urgency_ratios) if self.urgency_ratios else 0.0,
                'avg_queue_penalty': sum(self.queue_penalties) / len(self.queue_penalties) if self.queue_penalties else 0.0,
            },
            'mpr': {
                'selections': self.mpr_selections,
                'forwards': self.mpr_forwards,
            },
        }
    
    def reset(self):
        """Reset all metrics to initial state."""
        self.messages_sent.clear()
        self.messages_received.clear()
        self.messages_forwarded.clear()
        self.messages_dropped.clear()
        self.consumer_state_transitions.clear()
        self.ph_state_transitions.clear()
        self.rreh_state_transitions.clear()
        self.sessions_successful = 0
        self.sessions_failed = 0
        self.sessions_timeout = 0
        self.total_retries = 0
        self.total_blacklist_events = 0
        self.backoff_durations.clear()
        self.rreh_selections = 0
        self.platoon_selections = 0
        self.detour_costs.clear()
        self.urgency_ratios.clear()
        self.queue_penalties.clear()
        self.session_durations.clear()
        self.mpr_selections = 0
        self.mpr_forwards = 0
