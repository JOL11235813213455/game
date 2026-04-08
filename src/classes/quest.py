"""
Quest and QuestLog system.

Quests are defined in the DB (quests + quest_steps tables).
Each creature has a QuestLog that tracks active/completed/failed quests.

Conditions and actions are stored as Python expression strings,
evaluated against a restricted namespace for safety.
"""
from __future__ import annotations
from enum import Enum


class QuestState(Enum):
    AVAILABLE = 'available'     # conditions met, can be accepted
    ACTIVE = 'active'           # accepted, in progress
    COMPLETED = 'completed'     # all steps done
    FAILED = 'failed'           # failure condition triggered or timed out


# Restricted namespace for eval — only safe references allowed
_EVAL_FORBIDDEN = {'__import__', '__builtins__', 'exec', 'eval', 'compile',
                   'open', 'input', '__', 'globals', 'locals'}


def _safe_eval(expr: str, namespace: dict) -> bool:
    """Evaluate a condition expression safely.

    Returns True if the expression evaluates truthy, False otherwise.
    Empty/blank expressions always return True.
    """
    if not expr or not expr.strip():
        return True
    # Block dangerous constructs
    for forbidden in _EVAL_FORBIDDEN:
        if forbidden in expr:
            return False
    try:
        return bool(eval(expr, {'__builtins__': {}}, namespace))
    except Exception:
        return False


def _safe_exec(action: str, namespace: dict):
    """Execute an action string safely.

    Empty/blank actions are no-ops.
    """
    if not action or not action.strip():
        return
    for forbidden in _EVAL_FORBIDDEN:
        if forbidden in action:
            return
    try:
        exec(action, {'__builtins__': {}}, namespace)
    except Exception:
        pass


class QuestLog:
    """Per-creature quest tracking.

    Manages quest states, step progress, timers, and condition evaluation.
    """

    def __init__(self):
        self.quests: dict[str, dict] = {}
        # Each entry: {
        #   'state': QuestState,
        #   'steps_completed': set of (step_no, step_sub),
        #   'started_at': int (game tick),
        #   'step_timers': {(step_no, step_sub): start_tick},
        #   'completed_at': int or None,
        #   'cooldown_until': int or None,
        # }

    def accept_quest(self, quest_name: str, quest_def: dict, now: int) -> bool:
        """Accept a quest. Returns True if accepted.

        Args:
            quest_name: unique quest identifier
            quest_def: quest definition dict from QUESTS
            now: current game tick
        """
        # Check if already active
        if quest_name in self.quests:
            entry = self.quests[quest_name]
            if entry['state'] in (QuestState.ACTIVE,):
                return False
            # Repeatable quests can be re-accepted after completion
            if entry['state'] == QuestState.COMPLETED:
                if not quest_def.get('repeatable', False):
                    return False
                # Check cooldown
                cooldown = entry.get('cooldown_until')
                if cooldown and now < cooldown:
                    return False

        self.quests[quest_name] = {
            'state': QuestState.ACTIVE,
            'steps_completed': set(),
            'started_at': now,
            'step_timers': {},
            'completed_at': None,
            'cooldown_until': None,
        }
        return True

    def complete_step(self, quest_name: str, step_no: int, step_sub: str = 'a') -> bool:
        """Mark a quest step as completed. Returns True if marked."""
        entry = self.quests.get(quest_name)
        if entry is None or entry['state'] != QuestState.ACTIVE:
            return False
        entry['steps_completed'].add((step_no, step_sub))
        return True

    def is_step_complete(self, quest_name: str, step_no: int, step_sub: str = 'a') -> bool:
        """Check if a specific step is completed."""
        entry = self.quests.get(quest_name)
        if entry is None:
            return False
        return (step_no, step_sub) in entry['steps_completed']

    def check_quest_complete(self, quest_name: str, quest_steps: list[dict]) -> bool:
        """Check if all steps of a quest are completed.

        Args:
            quest_steps: list of step definition dicts for this quest
        """
        entry = self.quests.get(quest_name)
        if entry is None or entry['state'] != QuestState.ACTIVE:
            return False

        required = {(s['step_no'], s['step_sub']) for s in quest_steps}
        return required.issubset(entry['steps_completed'])

    def complete_quest(self, quest_name: str, now: int,
                       quest_def: dict = None) -> bool:
        """Mark quest as completed. Returns True if completed."""
        entry = self.quests.get(quest_name)
        if entry is None or entry['state'] != QuestState.ACTIVE:
            return False
        entry['state'] = QuestState.COMPLETED
        entry['completed_at'] = now
        # Set cooldown for repeatable quests
        if quest_def and quest_def.get('repeatable') and quest_def.get('cooldown_days'):
            entry['cooldown_until'] = now + quest_def['cooldown_days'] * 86_400_000
        return True

    def fail_quest(self, quest_name: str) -> bool:
        """Mark quest as failed. Returns True if failed."""
        entry = self.quests.get(quest_name)
        if entry is None or entry['state'] != QuestState.ACTIVE:
            return False
        entry['state'] = QuestState.FAILED
        return True

    def get_active_quests(self) -> list[str]:
        """Return list of active quest names."""
        return [name for name, e in self.quests.items()
                if e['state'] == QuestState.ACTIVE]

    def get_quest_state(self, quest_name: str) -> QuestState | None:
        """Return the state of a quest, or None if not in log."""
        entry = self.quests.get(quest_name)
        return entry['state'] if entry else None

    def check_time_limits(self, quest_name: str, quest_def: dict,
                          quest_steps: list[dict], now: int) -> bool:
        """Check if any time limits have been exceeded.

        Returns True if quest should be failed due to timeout.
        """
        entry = self.quests.get(quest_name)
        if entry is None or entry['state'] != QuestState.ACTIVE:
            return False

        # Overall quest time limit
        total_limit = quest_def.get('time_limit')
        if total_limit and (now - entry['started_at']) > total_limit * 1000:
            return True

        # Per-step time limits — only check reachable steps (prior steps done)
        for step in quest_steps:
            key = (step['step_no'], step['step_sub'])
            step_limit = step.get('time_limit')
            if step_limit and key not in entry['steps_completed']:
                # Only time steps that are reachable (all prior steps done)
                if step['step_no'] > 1:
                    prior_steps = [s for s in quest_steps if s['step_no'] == step['step_no'] - 1]
                    if not all((s['step_no'], s['step_sub']) in entry['steps_completed']
                               for s in prior_steps):
                        continue  # prior step not done — step not reachable yet
                timer_start = entry['step_timers'].get(key, entry['started_at'])
                if (now - timer_start) > step_limit * 1000:
                    return True

        return False

    def evaluate_conditions(self, quest_name: str, quest_def: dict,
                            quest_steps: list[dict], namespace: dict,
                            now: int) -> dict:
        """Evaluate all conditions for a quest and its steps.

        Returns dict with:
            available: bool (quest conditions met)
            steps: {(step_no, sub): {'success': bool, 'failed': bool}}
            timed_out: bool
        """
        result = {
            'available': _safe_eval(quest_def.get('conditions', ''), namespace),
            'steps': {},
            'timed_out': self.check_time_limits(quest_name, quest_def, quest_steps, now),
        }

        for step in quest_steps:
            key = (step['step_no'], step['step_sub'])
            # Prior step completion is implicit condition
            if step['step_no'] > 1:
                # Check all subs of prior step are done
                prior_no = step['step_no'] - 1
                prior_steps = [s for s in quest_steps if s['step_no'] == prior_no]
                prior_done = all(
                    (s['step_no'], s['step_sub']) in (self.quests.get(quest_name, {}).get('steps_completed', set()))
                    for s in prior_steps
                )
                if not prior_done:
                    result['steps'][key] = {'success': False, 'failed': False}
                    continue

            result['steps'][key] = {
                'success': _safe_eval(step.get('success_condition', ''), namespace),
                'failed': _safe_eval(step.get('fail_condition', ''), namespace),
            }

        return result

    def execute_action(self, action_str: str, namespace: dict):
        """Execute a quest action string (reward, failure, step action)."""
        _safe_exec(action_str, namespace)
