#!/bin/bash

# This script is used to delete old logs from the log directory.
# It removes log directories it deletes from logs.json.

die () {
  echo "$0 <directory> <max age (in days)>"
  exit 1
}

if [ -z $1 ] || [ -z $2 ] ; then
  die
fi

LOGDIR=$1
AGE=$2

find $LOGDIR -maxdepth 1 -type d -mtime +$AGE | while read line; do
  DIR=`basename $line`
  echo "Deleting $DIR"
  jq ". - [ \"$DIR\" ]" $LOGDIR/logs.json | sponge $LOGDIR/logs.json
  rm -rf $line
done
