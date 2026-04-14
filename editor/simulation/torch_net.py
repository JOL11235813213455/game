"""
PyTorch neural net for training. Mirrors CreatureNet architecture.

Used ONLY during training — the game loads weights into the NumPy
CreatureNet for runtime inference (no PyTorch dependency in-game).

Architecture: input → 1024 → 512 → 256 → 49 (policy head)
                                        → 1   (value head)
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from pathlib import Path

from classes.observation import OBSERVATION_SIZE
from classes.actions import NUM_ACTIONS


class TorchCreatureNet(nn.Module):
    """PyTorch version of CreatureNet for training with autograd.

    5 hidden layers (was 3): input -> 1536 -> 1024 -> 768 -> 384 -> 192
    -> {policy, value}. The wider top layer absorbs the new perception
    section (10 slots * 51 floats = 510 plus social topology and
    hearing) without bottlenecking the gradient. Roughly 5M parameters
    vs the previous ~2M.
    """

    def __init__(self, input_size: int = OBSERVATION_SIZE,
                 h1: int = 1536, h2: int = 1024, h3: int = 768,
                 h4: int = 384, h5: int = 192,
                 output_size: int = NUM_ACTIONS):
        super().__init__()
        self.fc1 = nn.Linear(input_size, h1)
        self.fc2 = nn.Linear(h1, h2)
        self.fc3 = nn.Linear(h2, h3)
        self.fc4 = nn.Linear(h3, h4)
        self.fc5 = nn.Linear(h4, h5)
        # Policy head: action probabilities
        self.policy_head = nn.Linear(h5, output_size)
        # Value head: state value estimate
        self.value_head = nn.Linear(h5, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass returning (action_logits, state_value)."""
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        x = F.relu(self.fc4(x))
        x = F.relu(self.fc5(x))
        logits = self.policy_head(x)
        value = self.value_head(x)
        return logits, value

    @staticmethod
    def _apply_action_mask(logits: torch.Tensor,
                           action_mask: np.ndarray | None) -> torch.Tensor:
        """Set logits for disallowed actions to -1e10 (pre-softmax)."""
        if action_mask is not None:
            mask_t = torch.FloatTensor(action_mask)
            if logits.dim() == 2:
                mask_t = mask_t.unsqueeze(0)
            logits = logits.masked_fill(mask_t == 0, -1e10)
        return logits

    def get_action(self, obs: np.ndarray, temperature: float = 1.0,
                   action_mask: np.ndarray | None = None,
                   ) -> tuple[int, float, float]:
        """Sample an action from observation.

        Args:
            action_mask: binary array of length NUM_ACTIONS where 1 =
                allowed, 0 = forbidden. None = all actions allowed.

        Returns (action, log_prob, value).
        """
        with torch.no_grad():
            x = torch.FloatTensor(obs).unsqueeze(0)
            logits, value = self.forward(x)
            if temperature != 1.0:
                logits = logits / max(0.01, temperature)
            logits = self._apply_action_mask(logits, action_mask)
            probs = F.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs)
            action = dist.sample()
            return action.item(), dist.log_prob(action).item(), value.item()

    def evaluate_actions(self, obs: torch.Tensor, actions: torch.Tensor,
                         action_masks: torch.Tensor | None = None,
                         ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Evaluate a batch of (obs, action) pairs.

        Args:
            action_masks: (batch, NUM_ACTIONS) binary tensor. None = all allowed.

        Returns (log_probs, values, entropy).
        """
        logits, values = self.forward(obs)
        if action_masks is not None:
            logits = logits.masked_fill(action_masks == 0, -1e10)
        probs = F.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()
        return log_probs, values.squeeze(-1), entropy

    def export_to_numpy(self, path: str | Path):
        """Export weights to .npz for NumPy CreatureNet to load.

        Layer numbering: w1..w5 = fc1..fc5, w_pol/b_pol = policy head,
        w_val/b_val = value head. Older 3-layer exports remain
        importable via import_from_numpy's backward-compat path.
        """
        state = self.state_dict()
        np_weights = {
            'w1': state['fc1.weight'].T.numpy(),
            'b1': state['fc1.bias'].numpy(),
            'w2': state['fc2.weight'].T.numpy(),
            'b2': state['fc2.bias'].numpy(),
            'w3': state['fc3.weight'].T.numpy(),
            'b3': state['fc3.bias'].numpy(),
            'w4': state['fc4.weight'].T.numpy(),
            'b4': state['fc4.bias'].numpy(),
            'w5': state['fc5.weight'].T.numpy(),
            'b5': state['fc5.bias'].numpy(),
            'w_pol': state['policy_head.weight'].T.numpy(),
            'b_pol': state['policy_head.bias'].numpy(),
            'w_val': state['value_head.weight'].T.numpy(),
            'b_val': state['value_head.bias'].numpy(),
        }
        np.savez(str(path), **np_weights)

    def import_from_numpy(self, path: str | Path):
        """Load weights from .npz. Handles two layouts:
          1. New 5-layer format with w1..w5 and w_pol/b_pol/w_val/b_val
          2. Legacy 3-layer format with w1..w4 (w4 is policy head)

        Input padding still works: if the saved w1 has fewer input
        columns than current fc1 expects, pads with zeros.
        """
        data = np.load(str(path))
        state = self.state_dict()

        # Handle input size change on w1 (stored transposed: in × h)
        w1_saved = data['w1']
        w1_target = state['fc1.weight']
        if w1_saved.shape[0] != w1_target.shape[1]:
            old_in, h1 = w1_saved.shape
            new_in = w1_target.shape[1]
            if new_in > old_in:
                padded = np.zeros((new_in, h1), dtype=np.float32)
                padded[:old_in, :] = w1_saved
                w1_saved = padded
            elif new_in < old_in:
                w1_saved = w1_saved[:new_in, :]
        state['fc1.weight'] = torch.FloatTensor(w1_saved.T)
        state['fc1.bias'] = torch.FloatTensor(data['b1'])
        state['fc2.weight'] = torch.FloatTensor(data['w2'].T)
        state['fc2.bias'] = torch.FloatTensor(data['b2'])
        state['fc3.weight'] = torch.FloatTensor(data['w3'].T)
        state['fc3.bias'] = torch.FloatTensor(data['b3'])

        if 'w5' in data.files:
            # New 5-layer format
            state['fc4.weight'] = torch.FloatTensor(data['w4'].T)
            state['fc4.bias'] = torch.FloatTensor(data['b4'])
            state['fc5.weight'] = torch.FloatTensor(data['w5'].T)
            state['fc5.bias'] = torch.FloatTensor(data['b5'])
            state['policy_head.weight'] = torch.FloatTensor(data['w_pol'].T)
            state['policy_head.bias'] = torch.FloatTensor(data['b_pol'])
            if 'w_val' in data.files:
                state['value_head.weight'] = torch.FloatTensor(data['w_val'].T)
                state['value_head.bias'] = torch.FloatTensor(data['b_val'])
        else:
            # Legacy 3-layer format: w4 was policy head. Leave fc4 and
            # fc5 at random initialization (effectively a partial
            # warm start that loses the old policy head's weights but
            # keeps the feature extractor).
            state['policy_head.weight'] = torch.FloatTensor(data['w4'].T)
            state['policy_head.bias'] = torch.FloatTensor(data['b4'])

        self.load_state_dict(state, strict=False)

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())


class TorchGoalNet(nn.Module):
    """PyTorch goal selection network for hierarchical RL training.

    Three hidden layers with LayerNorm for stable training across
    heterogeneous input scales. Deeper than before to capture
    interactions between urgency signals, schedule state, and
    spatial memory.
    """

    def __init__(self, input_size: int = None,
                 h1: int = 384, h2: int = 256, h3: int = 128,
                 output_size: int = None):
        super().__init__()
        from classes.goal_net import GOAL_OBSERVATION_SIZE
        from classes.actions import NUM_PURPOSES
        if input_size is None:
            input_size = GOAL_OBSERVATION_SIZE
        if output_size is None:
            output_size = NUM_PURPOSES
        self.fc1 = nn.Linear(input_size, h1)
        self.ln1 = nn.LayerNorm(h1)
        self.fc2 = nn.Linear(h1, h2)
        self.ln2 = nn.LayerNorm(h2)
        self.fc3 = nn.Linear(h2, h3)
        self.ln3 = nn.LayerNorm(h3)
        self.goal_head = nn.Linear(h3, output_size)
        self.value_head = nn.Linear(h3, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        x = F.relu(self.ln1(self.fc1(x)))
        x = F.relu(self.ln2(self.fc2(x)))
        x = F.relu(self.ln3(self.fc3(x)))
        return self.goal_head(x), self.value_head(x)

    def get_goal(self, obs: np.ndarray, known_purposes: set = None,
                 temperature: float = 1.0) -> tuple[int, float, float]:
        """Select a goal. Returns (goal_idx, log_prob, value)."""
        from classes.actions import TILE_PURPOSES
        with torch.no_grad():
            x = torch.FloatTensor(obs).unsqueeze(0)
            logits, value = self.forward(x)
            logits = logits.squeeze(0)

            # Mask unknown purposes
            if known_purposes is not None:
                for i, p in enumerate(TILE_PURPOSES):
                    if p not in known_purposes and p != 'exploring':
                        logits[i] -= 100.0

            if temperature != 1.0:
                logits = logits / max(0.01, temperature)

            probs = F.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs)
            goal = dist.sample()
            return goal.item(), dist.log_prob(goal).item(), value.item()

    def evaluate_goals(self, obs: torch.Tensor, goals: torch.Tensor):
        """Evaluate goals for PPO update. Returns (log_probs, values, entropy)."""
        logits, values = self.forward(obs)
        probs = F.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs)
        log_probs = dist.log_prob(goals)
        entropy = dist.entropy()
        return log_probs, values.squeeze(-1), entropy

    def export_to_numpy(self, path):
        """Export weights for GoalNet runtime inference."""
        state = self.state_dict()
        np_weights = {
            'gw1': state['fc1.weight'].T.numpy(),
            'gb1': state['fc1.bias'].numpy(),
            'gln1_g': state['ln1.weight'].numpy(),
            'gln1_b': state['ln1.bias'].numpy(),
            'gw2': state['fc2.weight'].T.numpy(),
            'gb2': state['fc2.bias'].numpy(),
            'gln2_g': state['ln2.weight'].numpy(),
            'gln2_b': state['ln2.bias'].numpy(),
            'gw3': state['fc3.weight'].T.numpy(),
            'gb3': state['fc3.bias'].numpy(),
            'gln3_g': state['ln3.weight'].numpy(),
            'gln3_b': state['ln3.bias'].numpy(),
            'gw_goal': state['goal_head.weight'].T.numpy(),
            'gb_goal': state['goal_head.bias'].numpy(),
        }
        np.savez(str(path), **np_weights)

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())


class PPO:
    """Proximal Policy Optimization with proper PyTorch autograd."""

    def __init__(self, net: TorchCreatureNet, lr: float = 3e-4,
                 gamma: float = 0.995, gae_lambda: float = 0.95,
                 clip_eps: float = 0.2, epochs: int = 4,
                 batch_size: int = 256, ent_coef: float = 0.05,
                 vf_coef: float = 0.5, max_grad_norm: float = 0.5):
        self.net = net
        self.gamma = gamma
        self.gae_lambda = gae_lambda
        self.clip_eps = clip_eps
        self.epochs = epochs
        self.batch_size = batch_size
        self.ent_coef = ent_coef
        self.vf_coef = vf_coef
        self.max_grad_norm = max_grad_norm
        self.optimizer = torch.optim.Adam(net.parameters(), lr=lr)

    def compute_gae(self, rewards, values, dones):
        """Generalized Advantage Estimation."""
        n = len(rewards)
        advantages = np.zeros(n, dtype=np.float32)
        last_gae = 0.0
        for t in reversed(range(n)):
            next_val = values[t + 1] if t < n - 1 else 0.0
            next_done = dones[t + 1] if t < n - 1 else 1.0
            delta = rewards[t] + self.gamma * next_val * (1 - next_done) - values[t]
            last_gae = delta + self.gamma * self.gae_lambda * (1 - next_done) * last_gae
            advantages[t] = last_gae
        returns = advantages + values[:n]
        return advantages, returns

    def update(self, obs_arr, actions_arr, rewards_arr, values_arr,
               log_probs_arr, dones_arr,
               action_masks_arr=None) -> dict:
        """Run PPO update on collected experience.

        All inputs are numpy arrays. action_masks_arr is optional
        (N, NUM_ACTIONS) binary array for per-step masking.
        Returns dict with loss metrics.
        """
        advantages, returns = self.compute_gae(rewards_arr, values_arr, dones_arr)

        # Normalize advantages
        advantages = (advantages - advantages.mean()) / (advantages.std() + 1e-8)

        # Convert to tensors
        obs_t = torch.FloatTensor(obs_arr)
        actions_t = torch.LongTensor(actions_arr)
        old_log_probs_t = torch.FloatTensor(log_probs_arr)
        advantages_t = torch.FloatTensor(advantages)
        returns_t = torch.FloatTensor(returns)
        masks_t = torch.FloatTensor(action_masks_arr) if action_masks_arr is not None else None

        n = len(obs_arr)
        total_policy_loss = 0.0
        total_value_loss = 0.0
        total_entropy = 0.0
        num_updates = 0

        for _ in range(self.epochs):
            indices = np.random.permutation(n)
            for start in range(0, n - self.batch_size + 1, self.batch_size):
                batch = indices[start:start + self.batch_size]

                b_obs = obs_t[batch]
                b_actions = actions_t[batch]
                b_old_lp = old_log_probs_t[batch]
                b_adv = advantages_t[batch]
                b_ret = returns_t[batch]
                b_masks = masks_t[batch] if masks_t is not None else None

                new_log_probs, values, entropy = self.net.evaluate_actions(
                    b_obs, b_actions, action_masks=b_masks)

                ratio = torch.exp(new_log_probs - b_old_lp)
                surr1 = ratio * b_adv
                surr2 = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * b_adv
                policy_loss = -torch.min(surr1, surr2).mean()

                value_loss = F.mse_loss(values, b_ret)
                entropy_loss = -entropy.mean()

                loss = policy_loss + self.vf_coef * value_loss + self.ent_coef * entropy_loss

                self.optimizer.zero_grad()
                loss.backward()
                nn.utils.clip_grad_norm_(self.net.parameters(), self.max_grad_norm)
                self.optimizer.step()

                total_policy_loss += policy_loss.item()
                total_value_loss += value_loss.item()
                total_entropy += entropy.mean().item()
                num_updates += 1

        return {
            'policy_loss': total_policy_loss / max(1, num_updates),
            'value_loss': total_value_loss / max(1, num_updates),
            'entropy': total_entropy / max(1, num_updates),
        }


class RolloutBuffer:
    """Collects experience during rollouts."""

    def __init__(self):
        self.obs = []
        self.actions = []
        self.rewards = []
        self.values = []
        self.log_probs = []
        self.dones = []
        self.action_masks = []

    def store(self, obs, action, reward, value, log_prob, done,
              action_mask=None):
        self.obs.append(obs)
        self.actions.append(action)
        self.rewards.append(reward)
        self.values.append(value)
        self.log_probs.append(log_prob)
        self.dones.append(1.0 if done else 0.0)
        if action_mask is not None:
            self.action_masks.append(action_mask)

    def get(self):
        base = (
            np.array(self.obs, dtype=np.float32),
            np.array(self.actions, dtype=np.int64),
            np.array(self.rewards, dtype=np.float32),
            np.array(self.values, dtype=np.float32),
            np.array(self.log_probs, dtype=np.float32),
            np.array(self.dones, dtype=np.float32),
        )
        if self.action_masks:
            return base + (np.array(self.action_masks, dtype=np.float32),)
        return base + (None,)

    def clear(self):
        self.obs.clear()
        self.actions.clear()
        self.rewards.clear()
        self.values.clear()
        self.log_probs.clear()
        self.dones.clear()
        self.action_masks.clear()

    def __len__(self):
        return len(self.obs)
