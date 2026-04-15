"""
Lightweight neural net for creature AI inference.

Pure NumPy — no PyTorch, TensorFlow, or other ML framework at runtime.
Small feedforward network: input → hidden1 → hidden2 → output.
Supports batched inference for all creatures in one forward pass.

Weights are loaded from a file (trained externally via RL harness).
"""
from __future__ import annotations
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
import numpy as np
from pathlib import Path
from classes.actions import NUM_ACTIONS
from classes.observation import OBSERVATION_SIZE


try:
    from fast_native.fast_math import c_relu as _c_relu, c_softmax as _c_softmax
    from fast_native.fast_math import c_forward_5layer
    _HAS_CYTHON = True
except ImportError:
    _HAS_CYTHON = False

def relu(x: np.ndarray) -> np.ndarray:
    return np.maximum(0, x)


def softmax(x: np.ndarray) -> np.ndarray:
    if x.ndim == 1:
        e = np.exp(x - x.max())
        return e / e.sum()
    e = np.exp(x - x.max(axis=1, keepdims=True))
    return e / e.sum(axis=1, keepdims=True)


class CreatureNet:
    """Feedforward neural net for creature action selection.

    Architecture: input -> 1536 -> 1024 -> 768 -> 384 -> 192 -> output
    Activation: ReLU on hidden layers, softmax on policy output.

    Five hidden layers (was 3). Width is widest at the top to absorb
    the new perception sections (10-slot, social topology, hearing,
    water awareness) and narrows as it approaches the action head.
    """

    def __init__(self, h1_size: int = 1536, h2_size: int = 1024,
                 h3_size: int = 768, h4_size: int = 384, h5_size: int = 192,
                 input_size: int = OBSERVATION_SIZE,
                 output_size: int = NUM_ACTIONS):
        self.input_size = input_size
        self.h1_size = h1_size
        self.h2_size = h2_size
        self.h3_size = h3_size
        self.h4_size = h4_size
        self.h5_size = h5_size
        self.output_size = output_size
        self.weights: dict[str, np.ndarray] = {}
        self._init_random()

    def _init_random(self):
        """Xavier initialization for weights."""
        s1 = np.sqrt(2.0 / (self.input_size + self.h1_size))
        s2 = np.sqrt(2.0 / (self.h1_size + self.h2_size))
        s3 = np.sqrt(2.0 / (self.h2_size + self.h3_size))
        s4 = np.sqrt(2.0 / (self.h3_size + self.h4_size))
        s5 = np.sqrt(2.0 / (self.h4_size + self.h5_size))
        sp = np.sqrt(2.0 / (self.h5_size + self.output_size))

        self.weights = {
            'w1': np.random.randn(self.input_size, self.h1_size).astype(np.float32) * s1,
            'b1': np.zeros(self.h1_size, dtype=np.float32),
            'w2': np.random.randn(self.h1_size, self.h2_size).astype(np.float32) * s2,
            'b2': np.zeros(self.h2_size, dtype=np.float32),
            'w3': np.random.randn(self.h2_size, self.h3_size).astype(np.float32) * s3,
            'b3': np.zeros(self.h3_size, dtype=np.float32),
            'w4': np.random.randn(self.h3_size, self.h4_size).astype(np.float32) * s4,
            'b4': np.zeros(self.h4_size, dtype=np.float32),
            'w5': np.random.randn(self.h4_size, self.h5_size).astype(np.float32) * s5,
            'b5': np.zeros(self.h5_size, dtype=np.float32),
            'w_pol': np.random.randn(self.h5_size, self.output_size).astype(np.float32) * sp,
            'b_pol': np.zeros(self.output_size, dtype=np.float32),
        }

    def forward(self, obs: np.ndarray) -> np.ndarray:
        """Forward pass. Accepts single observation or batch."""
        x = np.asarray(obs, dtype=np.float32)
        single = x.ndim == 1

        # Cython fast path for single observations
        if single and _HAS_CYTHON:
            w = self.weights
            return c_forward_5layer(
                np.ascontiguousarray(x, dtype=np.float32),
                np.ascontiguousarray(w['w1'], dtype=np.float32),
                np.ascontiguousarray(w['b1'], dtype=np.float32),
                np.ascontiguousarray(w['w2'], dtype=np.float32),
                np.ascontiguousarray(w['b2'], dtype=np.float32),
                np.ascontiguousarray(w['w3'], dtype=np.float32),
                np.ascontiguousarray(w['b3'], dtype=np.float32),
                np.ascontiguousarray(w['w4'], dtype=np.float32),
                np.ascontiguousarray(w['b4'], dtype=np.float32),
                np.ascontiguousarray(w['w5'], dtype=np.float32),
                np.ascontiguousarray(w['b5'], dtype=np.float32),
                np.ascontiguousarray(w['w_pol'], dtype=np.float32),
                np.ascontiguousarray(w['b_pol'], dtype=np.float32))

        if single:
            x = x.reshape(1, -1)
        x = relu(x @ self.weights['w1'] + self.weights['b1'])
        x = relu(x @ self.weights['w2'] + self.weights['b2'])
        x = relu(x @ self.weights['w3'] + self.weights['b3'])
        x = relu(x @ self.weights['w4'] + self.weights['b4'])
        x = relu(x @ self.weights['w5'] + self.weights['b5'])
        x = x @ self.weights['w_pol'] + self.weights['b_pol']
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
        """Load weights from a .npz file.

        Handles observation size changes: if saved w1 has fewer input
        rows than current input_size, extra rows are zero-padded.

        Backward compatible with the legacy 3-layer format (w1..w4
        where w4 was the policy head). When detected, fc4/fc5 stay
        at random init and only the input layers get warm-started.
        """
        data = np.load(str(path))
        legacy_format = 'w5' not in data.files

        # Always copy w1..w3 with input padding on w1
        for key in ('w1', 'b1', 'w2', 'b2', 'w3', 'b3'):
            if key not in data.files:
                continue
            saved = data[key].astype(np.float32)
            target = self.weights[key]
            if saved.shape == target.shape:
                self.weights[key] = saved
            elif key == 'w1' and saved.ndim == 2:
                old_in, h = saved.shape
                new_in = target.shape[0]
                if new_in > old_in and h == target.shape[1]:
                    padded = np.zeros(target.shape, dtype=np.float32)
                    padded[:old_in, :] = saved
                    self.weights[key] = padded
                elif new_in < old_in and h == target.shape[1]:
                    self.weights[key] = saved[:new_in, :]
            # else: shape mismatch on a hidden layer — keep random init

        if not legacy_format:
            # Modern format has w4, w5, w_pol/b_pol
            for key in ('w4', 'b4', 'w5', 'b5', 'w_pol', 'b_pol'):
                if key in data.files:
                    saved = data[key].astype(np.float32)
                    if saved.shape == self.weights[key].shape:
                        self.weights[key] = saved
        # Legacy format: fc4/fc5 stay random; old w4 was the policy head
        # but its shape no longer matches, so we leave the new w_pol
        # at random init too. Acceptable cold-start of the action head.

    def param_count(self) -> int:
        """Total number of trainable parameters."""
        return sum(w.size for w in self.weights.values())
