import os
import sys

import pytest


def pytest_collection_modifyitems(config, items):
    # Spark 3.5 hangs on Windows (no winutils.exe, Java > 17). Run these in Docker or CI instead:
    #   docker run --rm -v "$PWD:/app" transitpulse-spark python -m pytest tests/spark -m spark
    if sys.platform == "win32" and not os.environ.get("TP_SPARK_ON_WINDOWS"):
        skip = pytest.mark.skip(
            reason="Spark tests run in Docker/CI on Windows (see tests/spark/conftest.py)"
        )
        for item in items:
            if "spark" in item.keywords:
                item.add_marker(skip)
