#!/bin/bash

pylint toxicmaster/
if [ $? != "0" ]
then
    exit 1;
fi

flake8 toxicmaster/

if [ $? != "0" ]
then
    exit 1;
fi

flake8 tests
exit $?;
