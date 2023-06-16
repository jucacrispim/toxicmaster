#!/bin/bash
cd docs
export PYTHONPATH="$PWD/../"
rm -rf "$PWD/source/apidoc"
rm -rf "$PWD/build"
sphinx-apidoc -o "$PWD/source/apidoc" "$PWD/../toxiccore/"
make html
