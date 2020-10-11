#!/bin/bash

DIR=$(echo $(cd $(dirname "${BASH_SOURCE[0]}") && pwd -P))
DATA_DIR="${DIR}/data"
DB_FILE="${DATA_DIR}/deps.db/indexes.bolt"

if [ ! -f "${DB_FILE}" ]; then
  echo "DB File not found. Going to initialize from raw data dump."

  docker run \
    -v $DATA_DIR:/data \
    -p 64210:64210 \
    -u $(id -u ${USER}):$(id -g ${USER}) \
    cayleygraph/cayley:latest -c /data/deps.yml --init -i /data/deps.nq
else
  echo "DB File found. Going to use existing DB."

  docker run \
    -v $DATA_DIR:/data \
    -p 64210:64210 \
    -u $(id -u ${USER}):$(id -g ${USER}) \
    cayleygraph/cayley:latest -c /data/deps.yml
fi
