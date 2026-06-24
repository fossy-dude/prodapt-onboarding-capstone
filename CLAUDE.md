# Delegation
- Use parallel agents wherever possible for effectively using context window and accomplishing goals quickly
- Proactively delegate tasks like reading and summarizing from code/docs and answering one-off questions to sub-agents. This will keep your context clear. Frame clear tasks and expectations - and handover to sub-agents

## Testing

Integration and slow tests **skip by default** in both Python projects
(`service_webapp`, `cdr-pipeline`). 

- Run `just test` to run unit tests
- Run `just format` to run formatting
- Run `just lint` to run linter tests

For running python, always `cd` into the directory for the `service_backend` or `cdr-pipeline` first, and then run python from uv
by calling `uv run script.py` (replace script.py with the correct file)
