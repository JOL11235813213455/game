"""
JSONL sink for high-volume training data.

Writes per-episode and per-creature data to .jsonl files during training.
After a run completes, summarize() reads the sink and loads into training.db.

This decouples training speed from DB write speed.
"""
from __future__ import annotations
import json
import time
from pathlib import Path


class TrainingSink:
    """Buffered JSONL writer for training analytics."""

    def __init__(self, run_dir: Path, run_id: int = 0):
        self.run_dir = run_dir
        self.run_id = run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        self._episode_file = open(run_dir / 'episodes.jsonl', 'w')
        self._creature_file = open(run_dir / 'creatures.jsonl', 'w')
        self._phase_file = open(run_dir / 'phases.jsonl', 'w')
        self._sample_file = open(run_dir / 'samples.jsonl', 'w')

        # Accumulators for current episode
        self._ep_num = 0
        self._ep_rewards = []       # per-step rewards
        self._ep_breakdowns = {}    # signal_name -> cumulative
        self._ep_creature_data = {} # uid -> accumulator dict
        self._ep_action_counts = {} # action -> count
        self._ep_step_start = 0
        self._ep_step = 0

        # Phase accumulators
        self._phase_rewards = []
        self._phase_action_counts = {}
        self._phase_entropy = []
        self._phase_value_loss = []
        self._phase_deaths = 0
        self._phase_survival_steps = []
        self._phase_step_start = 0

    def close(self):
        """Flush and close all files."""
        for f in [self._episode_file, self._creature_file,
                  self._phase_file, self._sample_file]:
            if not f.closed:
                f.close()

    # --- Step-level recording ---

    def record_step(self, creature_uid: int, action: int, reward: float,
                    signals: dict | None = None, creature_name: str = '',
                    alive: bool = True):
        """Record a single step for a creature."""
        self._ep_step += 1
        self._ep_rewards.append(reward)
        self._phase_rewards.append(reward)

        # Action counts
        self._ep_action_counts[action] = self._ep_action_counts.get(action, 0) + 1
        self._phase_action_counts[action] = self._phase_action_counts.get(action, 0) + 1

        # Per-creature accumulation
        cd = self._ep_creature_data.get(creature_uid)
        if cd is None:
            cd = {
                'uid': creature_uid, 'name': creature_name,
                'total_reward': 0.0, 'steps': 0,
                'action_counts': {}, 'reward_breakdown': {},
                'alive': True,
            }
            self._ep_creature_data[creature_uid] = cd
        cd['total_reward'] += reward
        cd['steps'] += 1
        cd['alive'] = alive
        cd['action_counts'][action] = cd['action_counts'].get(action, 0) + 1

        # Signal breakdown accumulation
        if signals:
            for sig, val in signals.items():
                self._ep_breakdowns[sig] = self._ep_breakdowns.get(sig, 0) + val
                cd['reward_breakdown'][sig] = cd['reward_breakdown'].get(sig, 0) + val

    def record_training_update(self, entropy: float, value_loss: float,
                               policy_loss: float):
        """Record PPO update stats."""
        self._phase_entropy.append(entropy)
        self._phase_value_loss.append(value_loss)

    def record_sample(self, phase: str, global_step: int,
                      creature_uid: int, action: int, reward: float,
                      top_probs: dict = None, value_estimate: float = 0.0,
                      entropy: float = 0.0):
        """Write a Tier 5 time-series sample."""
        self._sample_file.write(json.dumps({
            'run_id': self.run_id, 'phase': phase,
            'step': global_step, 'uid': creature_uid,
            'action': action, 'reward': round(reward, 6),
            'top_probs': top_probs,
            'value': round(value_estimate, 4),
            'entropy': round(entropy, 4),
        }) + '\n')

    # --- Episode boundaries ---

    def end_episode(self, phase: str, cycle: int, alive_at_end: int,
                    total_creatures: int, arena_cols: int = 0,
                    arena_rows: int = 0,
                    creature_finals: dict = None):
        """Flush episode data to JSONL files.

        Args:
            creature_finals: {uid: {species, sex, profile, mask, hp_ratio,
                              gold, items, equipment, allies, enemies, kills,
                              tiles_explored, creatures_met, base_stats, ...}}
        """
        self._ep_num += 1
        creature_finals = creature_finals or {}

        # Track deaths for phase stats
        dead_count = total_creatures - alive_at_end
        self._phase_deaths += dead_count
        for cd in self._ep_creature_data.values():
            self._phase_survival_steps.append(cd['steps'])

        # Write episode summary
        ep_total = sum(self._ep_rewards)
        self._episode_file.write(json.dumps({
            'run_id': self.run_id, 'phase': phase, 'cycle': cycle,
            'episode': self._ep_num,
            'step_start': self._ep_step_start,
            'step_end': self._ep_step,
            'total_reward': round(ep_total, 4),
            'alive_at_end': alive_at_end,
            'total_creatures': total_creatures,
            'cols': arena_cols, 'rows': arena_rows,
            'reward_breakdown': {k: round(v, 4) for k, v in self._ep_breakdowns.items()},
        }) + '\n')

        # Write per-creature data
        for uid, cd in self._ep_creature_data.items():
            finals = creature_finals.get(uid, {})
            self._creature_file.write(json.dumps({
                'run_id': self.run_id, 'episode': self._ep_num,
                'uid': uid, 'name': cd['name'],
                'species': finals.get('species', ''),
                'sex': finals.get('sex', ''),
                'profile': finals.get('profile', ''),
                'mask': finals.get('mask'),
                'survived': cd['alive'],
                'survival_steps': cd['steps'],
                'total_reward': round(cd['total_reward'], 4),
                'reward_breakdown': {k: round(v, 4) for k, v in cd['reward_breakdown'].items()},
                'action_counts': cd['action_counts'],
                'final_hp_ratio': finals.get('hp_ratio'),
                'final_gold': finals.get('gold', 0),
                'final_items': finals.get('items', 0),
                'final_equipment': finals.get('equipment', 0),
                'final_allies': finals.get('allies', 0),
                'final_enemies': finals.get('enemies', 0),
                'kills': finals.get('kills', 0),
                'tiles_explored': finals.get('tiles_explored', 0),
                'creatures_met': finals.get('creatures_met', 0),
                'base_stats': finals.get('base_stats', {}),
            }) + '\n')

        # Reset episode accumulators
        self._ep_step_start = self._ep_step
        self._ep_rewards.clear()
        self._ep_breakdowns.clear()
        self._ep_creature_data.clear()
        self._ep_action_counts.clear()

    # --- Phase boundaries ---

    def end_phase(self, phase: str, cycle: int, step_start: int, step_end: int,
                  duration_secs: float):
        """Write phase summary to JSONL."""
        import numpy as np

        rewards = np.array(self._phase_rewards) if self._phase_rewards else np.array([0.0])
        survival = np.array(self._phase_survival_steps) if self._phase_survival_steps else np.array([0.0])

        self._phase_file.write(json.dumps({
            'run_id': self.run_id, 'phase': phase, 'cycle': cycle,
            'step_start': step_start, 'step_end': step_end,
            'duration_secs': round(duration_secs, 1),
            'reward_mean': round(float(np.mean(rewards)), 6),
            'reward_median': round(float(np.median(rewards)), 6),
            'reward_std': round(float(np.std(rewards)), 6),
            'reward_min': round(float(np.min(rewards)), 6),
            'reward_max': round(float(np.max(rewards)), 6),
            'reward_p10': round(float(np.percentile(rewards, 10)), 6),
            'reward_p90': round(float(np.percentile(rewards, 90)), 6),
            'action_distribution': self._phase_action_counts,
            'entropy_mean': round(float(np.mean(self._phase_entropy)), 6) if self._phase_entropy else None,
            'entropy_final': self._phase_entropy[-1] if self._phase_entropy else None,
            'value_loss_mean': round(float(np.mean(self._phase_value_loss)), 6) if self._phase_value_loss else None,
            'death_rate': self._phase_deaths / max(1, len(self._phase_survival_steps)),
            'avg_survival_steps': round(float(np.mean(survival)), 1),
            'episodes': self._ep_num,
        }) + '\n')

        # Reset phase accumulators
        self._phase_rewards.clear()
        self._phase_action_counts.clear()
        self._phase_entropy.clear()
        self._phase_value_loss.clear()
        self._phase_deaths = 0
        self._phase_survival_steps.clear()
        self._phase_step_start = step_end


def summarize_to_db(run_dir: Path, run_id: int):
    """Read JSONL sink files and load into training.db.

    Called after training completes.
    """
    from editor.simulation.training_db import get_con

    con = get_con()

    # Load phases
    phases_path = run_dir / 'phases.jsonl'
    if phases_path.exists():
        for line in phases_path.read_text().splitlines():
            d = json.loads(line)
            con.execute('''INSERT INTO phase_snapshots
                (run_id, phase, cycle, step_start, step_end, duration_secs,
                 reward_mean, reward_median, reward_std, reward_min, reward_max,
                 reward_p10, reward_p90, action_distribution,
                 entropy_mean, entropy_final, value_loss_mean,
                 death_rate, avg_survival_steps, episodes)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (run_id, d['phase'], d['cycle'], d['step_start'], d['step_end'],
                 d['duration_secs'], d['reward_mean'], d['reward_median'],
                 d['reward_std'], d['reward_min'], d['reward_max'],
                 d['reward_p10'], d['reward_p90'],
                 json.dumps(d['action_distribution']),
                 d.get('entropy_mean'), d.get('entropy_final'),
                 d.get('value_loss_mean'),
                 d.get('death_rate', 0), d.get('avg_survival_steps', 0),
                 d.get('episodes', 0)))

    # Load episodes
    episodes_path = run_dir / 'episodes.jsonl'
    episode_id_map = {}  # episode_num -> db_id
    if episodes_path.exists():
        for line in episodes_path.read_text().splitlines():
            d = json.loads(line)
            con.execute('''INSERT INTO episode_summaries
                (run_id, phase, cycle, episode_num, step_start, step_end,
                 total_reward, alive_at_end, total_creatures,
                 arena_cols, arena_rows, reward_breakdown)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)''',
                (run_id, d['phase'], d['cycle'], d['episode'],
                 d['step_start'], d['step_end'], d['total_reward'],
                 d['alive_at_end'], d['total_creatures'],
                 d.get('cols'), d.get('rows'),
                 json.dumps(d.get('reward_breakdown', {}))))
            episode_id_map[d['episode']] = con.execute('SELECT last_insert_rowid()').fetchone()[0]

    # Load creature episodes
    creatures_path = run_dir / 'creatures.jsonl'
    if creatures_path.exists():
        for line in creatures_path.read_text().splitlines():
            d = json.loads(line)
            ep_id = episode_id_map.get(d['episode'], 0)
            if not ep_id:
                continue
            con.execute('''INSERT INTO creature_episodes
                (episode_id, creature_uid, creature_name, species, sex, profile,
                 observation_mask, survived, survival_steps, total_reward,
                 reward_breakdown, action_counts, final_hp_ratio, final_gold,
                 final_items, final_equipment, final_allies, final_enemies,
                 kills, tiles_explored, creatures_met, base_stats)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                (ep_id, d['uid'], d.get('name', ''), d.get('species', ''),
                 d.get('sex', ''), d.get('profile', ''), d.get('mask'),
                 1 if d.get('survived', True) else 0, d.get('survival_steps', 0),
                 d['total_reward'],
                 json.dumps(d.get('reward_breakdown', {})),
                 json.dumps(d.get('action_counts', {})),
                 d.get('final_hp_ratio'), d.get('final_gold', 0),
                 d.get('final_items', 0), d.get('final_equipment', 0),
                 d.get('final_allies', 0), d.get('final_enemies', 0),
                 d.get('kills', 0), d.get('tiles_explored', 0),
                 d.get('creatures_met', 0),
                 json.dumps(d.get('base_stats', {}))))

    # Load samples
    samples_path = run_dir / 'samples.jsonl'
    if samples_path.exists():
        batch = []
        for line in samples_path.read_text().splitlines():
            d = json.loads(line)
            batch.append((run_id, d['phase'], d['step'], d.get('uid'),
                          d.get('action'), d.get('reward'),
                          json.dumps(d.get('top_probs')) if d.get('top_probs') else None,
                          d.get('value'), d.get('entropy')))
            if len(batch) >= 1000:
                con.executemany('''INSERT INTO step_samples
                    (run_id, phase, global_step, creature_uid, action, reward,
                     top_probs, value_estimate, entropy)
                    VALUES (?,?,?,?,?,?,?,?,?)''', batch)
                batch.clear()
        if batch:
            con.executemany('''INSERT INTO step_samples
                (run_id, phase, global_step, creature_uid, action, reward,
                 top_probs, value_estimate, entropy)
                VALUES (?,?,?,?,?,?,?,?,?)''', batch)

    con.commit()
    con.close()
