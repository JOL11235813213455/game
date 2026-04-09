"""
PyTorch neural net for training. Mirrors CreatureNet architecture.

Used ONLY during training — the game loads weights into the NumPy
CreatureNet for runtime inference (no PyTorch dependency in-game).

Architecture: input → 1024 → 512 → 256 → 49 (policy head)
                                        → 1   (value head)
"""
from __future__ import annotations
import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from pathlib import Path

from classes.observation import OBSERVATION_SIZE
from classes.actions import NUM_ACTIONS


class TorchCreatureNet(nn.Module):
    """PyTorch version of CreatureNet for training with autograd."""

    def __init__(self, input_size: int = OBSERVATION_SIZE,
                 h1: int = 1024, h2: int = 512, h3: int = 256,
                 output_size: int = NUM_ACTIONS):
        super().__init__()
        self.fc1 = nn.Linear(input_size, h1)
        self.fc2 = nn.Linear(h1, h2)
        self.fc3 = nn.Linear(h2, h3)
        # Policy head: action probabilities
        self.policy_head = nn.Linear(h3, output_size)
        # Value head: state value estimate
        self.value_head = nn.Linear(h3, 1)

    def forward(self, x: torch.Tensor) -> tuple[torch.Tensor, torch.Tensor]:
        """Forward pass returning (action_logits, state_value)."""
        x = F.relu(self.fc1(x))
        x = F.relu(self.fc2(x))
        x = F.relu(self.fc3(x))
        logits = self.policy_head(x)
        value = self.value_head(x)
        return logits, value

    def get_action(self, obs: np.ndarray, temperature: float = 1.0) -> tuple[int, float, float]:
        """Sample an action from observation.

        Returns (action, log_prob, value).
        """
        with torch.no_grad():
            x = torch.FloatTensor(obs).unsqueeze(0)
            logits, value = self.forward(x)
            if temperature != 1.0:
                logits = logits / max(0.01, temperature)
            probs = F.softmax(logits, dim=-1)
            dist = torch.distributions.Categorical(probs)
            action = dist.sample()
            return action.item(), dist.log_prob(action).item(), value.item()

    def evaluate_actions(self, obs: torch.Tensor, actions: torch.Tensor
                         ) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        """Evaluate a batch of (obs, action) pairs.

        Returns (log_probs, values, entropy).
        """
        logits, values = self.forward(obs)
        probs = F.softmax(logits, dim=-1)
        dist = torch.distributions.Categorical(probs)
        log_probs = dist.log_prob(actions)
        entropy = dist.entropy()
        return log_probs, values.squeeze(-1), entropy

    def export_to_numpy(self, path: str | Path):
        """Export weights to .npz for NumPy CreatureNet to load."""
        state = self.state_dict()
        np_weights = {
            'w1': state['fc1.weight'].T.numpy(),
            'b1': state['fc1.bias'].numpy(),
            'w2': state['fc2.weight'].T.numpy(),
            'b2': state['fc2.bias'].numpy(),
            'w3': state['fc3.weight'].T.numpy(),
            'b3': state['fc3.bias'].numpy(),
            'w4': state['policy_head.weight'].T.numpy(),
            'b4': state['policy_head.bias'].numpy(),
        }
        np.savez(str(path), **np_weights)

    def import_from_numpy(self, path: str | Path):
        """Load weights from .npz (NumPy CreatureNet format)."""
        data = np.load(str(path))
        state = self.state_dict()
        state['fc1.weight'] = torch.FloatTensor(data['w1'].T)
        state['fc1.bias'] = torch.FloatTensor(data['b1'])
        state['fc2.weight'] = torch.FloatTensor(data['w2'].T)
        state['fc2.bias'] = torch.FloatTensor(data['b2'])
        state['fc3.weight'] = torch.FloatTensor(data['w3'].T)
        state['fc3.bias'] = torch.FloatTensor(data['b3'])
        state['policy_head.weight'] = torch.FloatTensor(data['w4'].T)
        state['policy_head.bias'] = torch.FloatTensor(data['b4'])
        self.load_state_dict(state, strict=False)

    def param_count(self) -> int:
        return sum(p.numel() for p in self.parameters())


class PPO:
    """Proximal Policy Optimization with proper PyTorch autograd."""

    def __init__(self, net: TorchCreatureNet, lr: float = 3e-4,
                 gamma: float = 0.995, gae_lambda: float = 0.95,
                 clip_eps: float = 0.2, epochs: int = 4,
                 batch_size: int = 512, ent_coef: float = 0.01,
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
               log_probs_arr, dones_arr) -> dict:
        """Run PPO update on collected experience.

        All inputs are numpy arrays.
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

                # Evaluate current policy on batch
                new_log_probs, values, entropy = self.net.evaluate_actions(b_obs, b_actions)

                # Policy loss (clipped)
                ratio = torch.exp(new_log_probs - b_old_lp)
                surr1 = ratio * b_adv
                surr2 = torch.clamp(ratio, 1 - self.clip_eps, 1 + self.clip_eps) * b_adv
                policy_loss = -torch.min(surr1, surr2).mean()

                # Value loss
                value_loss = F.mse_loss(values, b_ret)

                # Entropy bonus (encourages exploration)
                entropy_loss = -entropy.mean()

                # Total loss
                loss = policy_loss + self.vf_coef * value_loss + self.ent_coef * entropy_loss

                # Backprop
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

    def store(self, obs, action, reward, value, log_prob, done):
        self.obs.append(obs)
        self.actions.append(action)
        self.rewards.append(reward)
        self.values.append(value)
        self.log_probs.append(log_prob)
        self.dones.append(1.0 if done else 0.0)

    def get(self):
        return (
            np.array(self.obs, dtype=np.float32),
            np.array(self.actions, dtype=np.int64),
            np.array(self.rewards, dtype=np.float32),
            np.array(self.values, dtype=np.float32),
            np.array(self.log_probs, dtype=np.float32),
            np.array(self.dones, dtype=np.float32),
        )

    def clear(self):
        self.obs.clear()
        self.actions.clear()
        self.rewards.clear()
        self.values.clear()
        self.log_probs.clear()
        self.dones.clear()

    def __len__(self):
        return len(self.obs)
