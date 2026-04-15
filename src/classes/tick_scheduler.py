"""
Tick scheduler for distributing creature updates across frames.

Instead of updating all 200 creatures every frame, the scheduler
spreads them across frames so only a subset processes each tick.
Each creature is assigned a phase based on its UID, ensuring even
distribution regardless of spawn order.

Usage:
    scheduler = TickScheduler(creatures, max_per_frame=20)
    # Each game frame:
    for creature in scheduler.due_this_frame(frame_number):
        creature.update(now, cols, rows)
"""
from __future__ import annotations


class TickScheduler:
    """Distributes creature updates across frames."""

    def __init__(self, max_per_frame: int = 20):
        self.max_per_frame = max_per_frame
        self._frame = 0

    def due_this_frame(self, creatures: list, frame: int = None) -> list:
        """Return the subset of creatures that should update this frame.

        Distributes evenly: with 100 creatures and max_per_frame=20,
        each creature updates every 5th frame.
        """
        if frame is not None:
            self._frame = frame
        else:
            self._frame += 1

        n = len(creatures)
        if n <= self.max_per_frame:
            return creatures

        # Number of frames in the rotation cycle
        cycle = max(1, (n + self.max_per_frame - 1) // self.max_per_frame)
        phase = self._frame % cycle
        return [c for i, c in enumerate(creatures) if i % cycle == phase]
