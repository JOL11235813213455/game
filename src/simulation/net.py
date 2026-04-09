"""
Lightweight neural net for creature AI inference.

Pure NumPy — no PyTorch, TensorFlow, or other ML framework at runtime.
Small feedforward network: input → hidden1 → hidden2 → output.
Supports batched inference for all creatures in one forward pass.

Weights are loaded from a file (trained externally via RL harness).
"""
from __future__ import annotations
import numpy as np
from pathlib import Path
from classes.actions import NUM_ACTIONS
from classes.observation import OBSERVATION_SIZE


def relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0, x)


def softmax(x: np.ndarray) -> np.ndarray:
    """Row-wise softmax for 2D array, or simple softmax for 1D."""
    if x.ndim == 1:
        e = np.exp(x - x.max())
        return e / e.sum()
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class CreatureNet:
    """Feedforward neural net for creature action selection.

    Architecture: input → hidden1(1024) → hidden2(512) → hidden3(256) → output(49)
    Activation: ReLU on hidden layers, softmax on output (action probabilities).

    Three hidden layers:
      Layer 1: "what's happening" — compress raw perception into abstract features
      Layer 2: "what matters" — combine features into situational assessment
      Layer 3: "which action" — map assessment to behavioral intent
    """

    def __init__(self, h1_size: int = 1024, h2_size: int = 512,
                 h3_size: int = 256,
                 input_size: int = OBSERVATION_SIZE,
                 output_size: int = NUM_ACTIONS):
        self.input_size = input_size
        self.h1_size = h1_size
        self.h2_size = h2_size
        self.h3_size = h3_size
        self.output_size = output_size
        self.weights: dict[str, np.ndarray] = {}
        self._init_random()

    def _init_random(self):
        """Xavier initialization for weights."""
        s1 = np.sqrt(2.0 / (self.input_size + self.h1_size))
        s2 = np.sqrt(2.0 / (self.h1_size + self.h2_size))
        s3 = np.sqrt(2.0 / (self.h2_size + self.h3_size))
        s4 = np.sqrt(2.0 / (self.h3_size + self.output_size))

        self.weights = {
            'w1': np.random.randn(self.input_size, self.h1_size).astype(np.float32) * s1,
            'b1': np.zeros(self.h1_size, dtype=np.float32),
            'w2': np.random.randn(self.h1_size, self.h2_size).astype(np.float32) * s2,
            'b2': np.zeros(self.h2_size, dtype=np.float32),
            'w3': np.random.randn(self.h2_size, self.h3_size).astype(np.float32) * s3,
            'b3': np.zeros(self.h3_size, dtype=np.float32),
            'w4': np.random.randn(self.h3_size, self.output_size).astype(np.float32) * s4,
            'b4': np.zeros(self.output_size, dtype=np.float32),
        }

    def forward(self, obs: np.ndarray) -> np.ndarray:
        """Forward pass. Accepts single observation or batch.

        Args:
            obs: (input_size,) or (batch, input_size) float32 array

        Returns:
            (output_size,) or (batch, output_size) action probabilities
        """
        x = np.asarray(obs, dtype=np.float32)
        single = x.ndim == 1
        if single:
            x = x.reshape(1, -1)

        x = relu(x @ self.weights['w1'] + self.weights['b1'])
        x = relu(x @ self.weights['w2'] + self.weights['b2'])
        x = relu(x @ self.weights['w3'] + self.weights['b3'])
        x = x @ self.weights['w4'] + self.weights['b4']
        probs = softmax(x)

        return probs[0] if single else probs

    def select_action(self, obs: np.ndarray, temperature: float = 1.0) -> int:
        """Sample an action from the probability distribution.

        Args:
            obs: single observation vector
            temperature: >1 = more random, <1 = more greedy, 0 = argmax

        Returns:
            action index (int)
        """
        probs = self.forward(obs)
        if temperature == 0:
            return int(np.argmax(probs))
        if temperature != 1.0:
            logits = np.log(probs + 1e-8) / temperature
            probs = softmax(logits)
        return int(np.random.choice(len(probs), p=probs))

    def batch_select(self, obs_batch: np.ndarray,
                     temperature: float = 1.0) -> list[int]:
        """Select actions for a batch of observations.

        Args:
            obs_batch: (batch, input_size) array
            temperature: sampling temperature

        Returns:
            list of action indices
        """
        probs = self.forward(obs_batch)
        if temperature == 0:
            return [int(i) for i in np.argmax(probs, axis=1)]
        if temperature != 1.0:
            logits = np.log(probs + 1e-8) / temperature
            probs = softmax(logits)
        actions = []
        for p in probs:
            actions.append(int(np.random.choice(len(p), p=p)))
        return actions

    def save(self, path: str | Path):
        """Save weights to a .npz file."""
        np.savez(str(path), **self.weights)

    def load(self, path: str | Path):
        """Load weights from a .npz file."""
        data = np.load(str(path))
        for key in self.weights:
            if key in data:
                self.weights[key] = data[key].astype(np.float32)

    def param_count(self) -> int:
        """Total number of trainable parameters."""
        return sum(w.size for w in self.weights.values())
