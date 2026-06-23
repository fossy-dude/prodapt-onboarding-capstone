/caveman

## Testing

Integration and slow tests **skip by default** in both Python projects
(`service_webapp`, `cdr-pipeline`). 

Run `just test` to run unit tests (`cd` into the directory first)

For running python, always `cd` into the directory for the `service_backend` or `cdr-pipeline` first, and then run python from uv
by calling `uv run script.py` (replace script.py with the correct file)
