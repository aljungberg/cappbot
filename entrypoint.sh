#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

sleep 10

while true
do
    PYTHONPATH=$PWD exec python main/cappbot.py --settings "$SETTINGS" -v $*
	sleep 150
done
