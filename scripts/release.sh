#!/bin/bash

rm -rf dist/

python -m build

cd dist

fname=`ls | grep tar`
project_name=toxicmaster

curl -F file=@$fname -F prefix=$project_name https://pypi.poraodojuca.dev/u/ -H "Authorization: Key $PYPI_AUTH_KEY"
