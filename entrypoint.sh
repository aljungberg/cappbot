#!/bin/bash
set -euo pipefail
IFS=$'\n\t'

sleep 1

while true
do
    PYTHONPATH=$PWD exec python main/cappbot.py --settings settings.py -v $*
	sleep 150
done
