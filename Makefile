# The host has a ROS pytest plugin on PYTHONPATH that breaks collection;
# PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 keeps pytest from loading it.
TEST_ENV = PYTEST_DISABLE_PLUGIN_AUTOLOAD=1

.PHONY: test run install

test:
	$(TEST_ENV) python3 -m pytest -q

run:
	python3 -m uvicorn app.main:app --host 0.0.0.0 --port 8000

install:
	python3 -m pip install -r requirements.txt
