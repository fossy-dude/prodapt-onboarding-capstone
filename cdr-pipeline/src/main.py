"""CDR pipeline consumer entrypoint.

Story 1.3 establishes the project tooling baseline; the aiokafka consumer, balance
engine and fraud pre-screener land in Epic 2 (``python -m src.main`` / ``just cdr``).
"""


def main() -> None:
    """Run the CDR pipeline entrypoint.

    Epic 2 replaces this stub with the async Kafka consumer loop.
    """
    print("Hello from cdr-pipeline!")


if __name__ == "__main__":
    main()
