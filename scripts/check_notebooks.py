"""Execute notebooks in memory and report errors/stderr. Files are not modified.

Usage: uv run python scripts/check_notebooks.py notebooks/*.ipynb
Note: notebooks run with cwd=notebooks/ and may (re)write files in data/ and models/.
"""
import sys

import nbformat
from nbclient import NotebookClient

failed = False
for path in sys.argv[1:]:
    nb = nbformat.read(path, as_version=4)
    NotebookClient(nb, timeout=300, kernel_name="python3", allow_errors=True,
                   resources={"metadata": {"path": "notebooks"}}).execute()
    outputs = [(i, o) for i, c in enumerate(nb.cells) if c.cell_type == "code" for o in c.get("outputs", [])]
    errors = [(i, o) for i, o in outputs if o.get("output_type") == "error"]
    stderr = [(i, o) for i, o in outputs if o.get("name") == "stderr"]
    print(f"== {path}: {len(errors)} errors")
    for i, o in errors:
        print(f"  ERR cell {i}: {o['ename']}: {o['evalue']}")
    for i, o in stderr:
        print(f"  STDERR cell {i}: {o['text'][:300]}")
    failed |= bool(errors)
sys.exit(1 if failed else 0)
