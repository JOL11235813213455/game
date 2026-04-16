"""
MonsterNet — shared neural net across all monster species.

Architecture: input → 256 → 128 → 64 → output (11 action logits)
Smaller than CreatureNet because:
  - Monster observation is ~73 floats (vs creature ~1837)
  - Monster action space is 11 (vs creature 32)
  - Reward space is simpler (no social/economic signals)
  - Low-INT species use a fraction of the action space anyway

Species embedding: the observation already includes size_norm and diet
one-hot, so a single net can generalize across species without a
separate embedding table. This can be extended later if cross-species
signals need explicit separation.

Pure NumPy, same pattern as CreatureNet. Softmax policy head.
"""
from __future__ import annotations
import numpy as np
from pathlib import Path
from classes.monster_actions import NUM_MONSTER_ACTIONS
from classes.monster_observation import MONSTER_OBSERVATION_SIZE


def relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0, x)


def softmax(x: np.ndarray) -> np.ndarray:
    if x.ndim == 1:
        e = np.exp(x - x.max())
        return e / e.sum()
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class MonsterNet:
    """Feedforward NN for monster action selection."""

    def __init__(self, h1_size: int = 256, h2_size: int = 128, h3_size: int = 64,
                 input_size: int = MONSTER_OBSERVATION_SIZE,
                 output_size: int = NUM_MONSTER_ACTIONS):
        self.input_size = input_size
        self.h1_size = h1_size
        self.h2_size = h2_size
        self.h3_size = h3_size
        self.output_size = output_size
        self.weights: dict[str, np.ndarray] = {}
        self._init_random()

    def _init_random(self):
        """Xavier initialization."""
        s1 = np.sqrt(2.0 / (self.input_size + self.h1_size))
        s2 = np.sqrt(2.0 / (self.h1_size + self.h2_size))
        s3 = np.sqrt(2.0 / (self.h2_size + self.h3_size))
        sp = np.sqrt(2.0 / (self.h3_size + self.output_size))
        self.weights = {
            'w1': np.random.randn(self.input_size, self.h1_size).astype(np.float32) * s1,
            'b1': np.zeros(self.h1_size, dtype=np.float32),
            'w2': np.random.randn(self.h1_size, self.h2_size).astype(np.float32) * s2,
            'b2': np.zeros(self.h2_size, dtype=np.float32),
            'w3': np.random.randn(self.h2_size, self.h3_size).astype(np.float32) * s3,
            'b3': np.zeros(self.h3_size, dtype=np.float32),
            'w_pol': np.random.randn(self.h3_size, self.output_size).astype(np.float32) * sp,
            'b_pol': np.zeros(self.output_size, dtype=np.float32),
        }

    def forward(self, obs: np.ndarray) -> np.ndarray:
        x = np.asarray(obs, dtype=np.float32)
        single = x.ndim == 1
        if single:
            x = x.reshape(1, -1)
        x = relu(x @ self.weights['w1'] + self.weights['b1'])
        x = relu(x @ self.weights['w2'] + self.weights['b2'])
        x = relu(x @ self.weights['w3'] + self.weights['b3'])
        x = x @ self.weights['w_pol'] + self.weights['b_pol']
        probs = softmax(x)
        return probs[0] if single else probs

    def select_action(self, obs: np.ndarray, mask: np.ndarray | None = None,
                      temperature: float = 1.0) -> int:
        """Sample action with optional mask."""
        probs = self.forward(obs)
        if mask is not None:
            probs = probs * mask
            total = probs.sum()
            if total > 0:
                probs = probs / total
            else:
                # fallback: uniform over mask
                probs = mask / mask.sum() if mask.sum() > 0 else np.ones_like(probs) / len(probs)
        if temperature == 0:
            return int(np.argmax(probs))
        if temperature != 1.0:
            logits = np.log(probs + 1e-8) / temperature
            logits -= logits.max()
            probs = np.exp(logits)
            probs /= probs.sum()
        return int(np.random.choice(len(probs), p=probs))

    def save(self, path: str | Path):
        np.savez(str(path), **self.weights)

    def load(self, path: str | Path):
        data = np.load(str(path))
        for key in self.weights:
            if key in data.files:
                arr = data[key]
                if arr.shape == self.weights[key].shape:
                    self.weights[key] = arr.astype(np.float32)
