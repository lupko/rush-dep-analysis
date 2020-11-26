#!/bin/bash

set -e

if [ ! -d ".venv" ]; then
  echo "Creating virtual env and installing dependencies"
  virtualenv -p python3 .venv
  .venv/bin/pip install -r requirements.txt
fi

.venv/bin/python graph/discovery.py $*

rm -rf $2/deps.sqlite
.venv/bin/python graph/convert_graph.py $2/deps.nq $2/deps
