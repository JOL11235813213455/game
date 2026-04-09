#!/bin/bash
# Launch TensorBoard to view training metrics
# Usage: ./tensorboard.sh
cd "$(dirname "$0")/src"
echo "TensorBoard: http://localhost:6006"
tensorboard --logdir runs --port 6006 --bind_all
