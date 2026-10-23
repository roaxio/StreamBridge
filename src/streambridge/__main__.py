import sys

from streambridge import cli


def main() -> int:
    """`python -m streambridge`: delegate to the CLI host."""
    return cli.main()


if __name__ == "__main__":
    sys.exit(main())
