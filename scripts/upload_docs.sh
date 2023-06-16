#!/bin/bash

project=toxicsecrets
cd docs/build
mv html $project
tar -czf docs.tar.gz $project

curl --user "$TUPI_USER:$TUPI_PASSWD" -F 'file=@docs.tar.gz' https://docs.poraodojuca.dev/e/
