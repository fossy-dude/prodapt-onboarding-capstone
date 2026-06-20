"""Application entrypoint for the ``service_webapp`` backend.

Story 1.3 establishes the project tooling baseline; the FastAPI application and
middleware are wired up in Story 1.4.
"""

from fastapi import FastAPI

app = FastAPI(title="SBOAI Capstone", version="0.1.0")


@app.get("/")
def health() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok"}


def main() -> None:
    """Run the application entrypoint.

    Story 1.4 replaces this stub with the full FastAPI/uvicorn boot sequence.
    """
    print("Hello from service-webapp!")


if __name__ == "__main__":
    main()
