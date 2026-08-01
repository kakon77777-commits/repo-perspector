# Parser plugin example

Install the main project and this example in the same environment:

```bash
python -m pip install -e ../..
python -m pip install -e .
repo-perspector analyze /path/to/repository -o report
```

The package registers `DemoParser` through the `repo_perspector.parsers` entry-point group. External parsers should be stateless or thread-safe when analysis uses more than one worker.
