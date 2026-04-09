#!/bin/bash
# Launch training with TensorBoard
# Usage: ./train.sh [--cycles N] [--mappo-steps N] [--ppo-steps N]
cd "$(dirname "$0")/src"

echo "Starting TensorBoard..."
tensorboard --logdir runs --port 6006 --bind_all &
TB_PID=$!
echo "TensorBoard: http://localhost:6006"
echo ""

echo "Starting training..."
python -u -m simulation.train "$@" 2>&1 | tee models/training_log.txt

echo ""
echo "Training done. TensorBoard still running at http://localhost:6006"
echo "Press Ctrl+C to stop TensorBoard"
wait $TB_PID
