"""Entry point for `python -m roku_tui`."""

from roku_tui.app import RokuTUIApp


def main() -> None:
    app = RokuTUIApp()
    app.run()


if __name__ == "__main__":
    main()
