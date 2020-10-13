#!/bin/bash

DIR=$(echo $(cd $(dirname "${BASH_SOURCE[0]}") && pwd -P))
DATA_DIR="${DIR}/data"

docker run \
  -u $(id -u ${USER}):$(id -g ${USER}) \
  -e POSTGRES_PASSWORD=deps123 \
  -e PGDATA=/var/lib/postgresql/data/pgdata \
  -v ${DATA_DIR}:/var/lib/postgresql/data \
  -p 15432:5432 \
  postgres
