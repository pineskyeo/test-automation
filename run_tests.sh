#!/usr/bin/env bash
set -e
PYTHONPATH="$(cd "$(dirname "$0")" && pwd)" python tests/test_prototype_parser_regression.py
