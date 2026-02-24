# Roku TUI

A terminal-based remote control for your Roku devices. Because who needs the actual remote when you have a keyboard?

Roku TUI discovers devices on your network, gives you full remote control, and lets you launch your favorite apps — all without leaving the terminal.

## Features

- **Auto-Discovery** — Finds Roku devices on your network via SSDP multicast
- **Manual Connection** — Connect by IP address if discovery doesn't cut it
- **Full Remote Control** — Navigation, media playback, volume, and power controls
- **Favorite Apps** — Pin up to 5 apps per device for quick-launch with a single keypress
- **App Browser** — Browse and launch any installed app or channel
- **Private Listening** — Stream audio from your Roku to your computer's speakers/headphones
- **Persistent Storage** — Remembers your devices and favorites across sessions
- **Keyboard-Driven** — Every action mapped to a keystroke
- **Mouse Support** — Click the buttons if that's more your speed

## Installation

**Requirements:** Python 3.11+

```bash
git clone https://github.com/sloanb/roku-tui.git
cd roku-tui
pip install .
```

For private listening (audio streaming) support:

```bash
pip install ".[audio]"
```

This requires `libportaudio2` and `libopus0` system packages on Linux:

```bash
# Debian/Ubuntu
sudo apt install libportaudio2 libopus0

# Arch
sudo pacman -S portaudio opus
```

For development:

```bash
pip install -e ".[dev]"
```

## Usage

```bash
roku-tui
```

Or run as a module:

```bash
python -m roku_tui
```

On launch, Roku TUI scans your network for devices. Select one to connect and you're in.

## Keyboard Shortcuts

### Navigation

| Key | Action |
|-----|--------|
| `Arrow Keys` | D-pad navigation |
| `Enter` | Select / OK |
| `h` | Home |
| `b` | Back |
| `i` | Info |
| `p` | Power toggle |

### Media

| Key | Action |
|-----|--------|
| `Space` | Play / Pause |
| `r` | Rewind |
| `f` | Fast Forward |

### Volume

| Key | Action |
|-----|--------|
| `=` | Volume Up |
| `-` | Volume Down |
| `m` | Mute / Unmute |

### Apps & Favorites

| Key | Action |
|-----|--------|
| `1`–`5` | Launch favorite app |
| `g` | Open app browser |

### Audio

| Key | Action |
|-----|--------|
| `l` | Toggle private listening |

### General

| Key | Action |
|-----|--------|
| `s` | Scan for devices |
| `a` | Enter IP address manually |
| `Esc` | Go back |
| `q` | Quit |

## How It Works

Roku TUI communicates with your Roku devices over the [External Control Protocol (ECP)](https://developer.roku.com/docs/developer-program/dev-tools/external-control-api.md) — a REST API that Roku exposes on port 8060. Device discovery uses SSDP multicast, the same mechanism your phone's Roku app uses to find devices.

Private listening uses the ECP-2 WebSocket session protocol to authenticate and request an audio stream. The Roku sends Opus-encoded audio over RTP, which is decoded and played through your local audio output — the same mechanism the official Roku mobile app uses.

Your device list, favorites, and app cache are stored in `~/.config/roku-tui/devices.json` following the XDG base directory specification.

## Tech Stack

- [Textual](https://textual.textualize.io/) — TUI framework
- [httpx](https://www.python-httpx.org/) — Async HTTP client
- [websockets](https://websockets.readthedocs.io/) — ECP-2 WebSocket client (optional, for private listening)
- [sounddevice](https://python-sounddevice.readthedocs.io/) — Audio output (optional)
- [opuslib](https://github.com/OnBeep/opuslib) — Opus decoder (optional)
- [Hatchling](https://hatch.pypa.io/) — Build system

## Development

Run the test suite:

```bash
pytest
```

With coverage:

```bash
pytest --cov=roku_tui --cov-report=term-missing
```

## License

MIT
