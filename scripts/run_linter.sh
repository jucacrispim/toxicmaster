#!/bin/bash

pylint toxicnotifications/
if [ $? != "0" ]
then
    exit 1;
fi

flake8 toxicnotifications/

if [ $? != "0" ]
then
    exit 1;
fi

flake8 tests
exit $?;
