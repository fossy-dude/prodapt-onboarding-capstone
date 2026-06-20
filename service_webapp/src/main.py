"""Application entrypoint for the ``service_webapp`` backend.

Story 1.3 establishes the project tooling baseline; the FastAPI application and
middleware are wired up in Story 1.4 (``uvicorn src.main:app``).
"""


def main() -> None:
    """Run the application entrypoint.

    Story 1.4 replaces this stub with the FastAPI/uvicorn boot sequence.
    """
    print("Hello from service-webapp!")


if __name__ == "__main__":
    main()
