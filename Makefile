VERSION=$(shell python3 -c 'import tubeupac; print(tubeupac.__version__)')

binary:
	pex . --python=python3 --python-shebang='/usr/bin/env python3' -e tubeupac.__main__:main  -o tubeupac-$(VERSION)-py2.py3-none-any.pex

clean-pyc:
	find . -name '*.pyc' -exec rm -f {} +
	find . -name '*.pyo' -exec rm -f {} +
	find . -name '*~' -exec rm -f {} +
	find . -name '__pycache__' -exec rm -fr {} +

release-check:
	.venv/bin/python -B .claude/hooks/pypi_publish.py --dry-run

test: clean-pyc
	.venv/bin/pytest --cov
