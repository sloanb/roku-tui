# Roku TUI User Manual

Control your Roku devices from the terminal.

---

## Table of Contents

1. [Installation](#installation)
2. [Quick Start](#quick-start)
3. [Device Discovery & Connection](#device-discovery--connection)
   - [Network Scan](#network-scan)
   - [Manual IP Connection](#manual-ip-connection)
   - [Saved Devices](#saved-devices)
4. [Remote Control](#remote-control)
   - [Keyboard Shortcuts](#keyboard-shortcuts)
   - [On-Screen Buttons](#on-screen-buttons)
5. [Favorite Apps](#favorite-apps)
   - [Managing Favorites](#managing-favorites)
   - [Using Favorites](#using-favorites)
6. [Persistent Storage](#persistent-storage)
   - [Configuration Directory](#configuration-directory)
   - [Saved Device Data](#saved-device-data)
7. [Troubleshooting](#troubleshooting)
   - [Error Code Reference](#error-code-reference)
   - [Common Issues](#common-issues)

---

## Installation

### Requirements

- Python 3.11 or later
- A Roku device on your local network

### Install from Source

```bash
git clone <repository-url>
cd roku-tui
pip install .
```

For development (includes test dependencies):

```bash
pip install -e ".[dev]"
```

---

## Quick Start

Launch the application:

```bash
roku-tui
```

Or run as a Python module:

```bash
python -m roku_tui
```

Once launched:

1. Press **s** to scan your network for Roku devices.
2. Select a device from the list and press **Enter**.
3. Use your keyboard to control the Roku -- arrow keys to navigate, Enter to select, Space to play/pause.
4. Press **Esc** to return to the device list. Press **q** to quit.

Your device is automatically saved so it appears on next launch without scanning.

---

## Device Discovery & Connection

When Roku TUI starts, you see the **Device Screen**. This is where you find and connect to Roku devices.

### Network Scan

Press **s** or click the **Scan Network** button to search your local network. The scan sends an SSDP multicast query and waits 5 seconds for Roku devices to respond.

Discovered devices appear in the list showing their name, model, and IP address:

```
  Living Room Roku  --  Roku Streaming Stick 4K  (192.168.1.100)
```

Select a device with the arrow keys and press **Enter** to open the remote control.

### Manual IP Connection

If network scanning doesn't find your device (common behind firewalls or on segmented networks), you can connect directly by IP address.

1. Press **a** to focus the IP input field (or click it).
2. Type the device's IP address.
3. Press **Enter** or click **Connect**.

**Accepted formats:**

| Input | Result |
|-------|--------|
| `192.168.1.100` | Connects on default port 8060 |
| `192.168.1.100:8060` | Explicit port |
| `192.168.1.100:9000` | Custom port |

The application queries the device for its name, model, and serial number. On success, the device is added to the list and saved for future sessions.

### Saved Devices

Devices you've previously connected to are remembered across sessions. When you launch the app, saved devices appear automatically in the list with a **(saved)** indicator:

```
  Living Room Roku  --  Roku Streaming Stick 4K  (192.168.1.100) (saved)
```

You can select a saved device immediately without scanning. If you then scan, discovered devices are merged with your saved list -- no duplicates are created. If a device's IP address has changed since it was saved, the stored entry is updated automatically.

### Device Screen Keybindings

| Key | Action |
|-----|--------|
| **s** | Scan network for Roku devices |
| **a** | Focus the IP address input field |
| **q** | Quit the application |

---

## Remote Control

After selecting a device, the **Remote Screen** opens. This screen mimics a physical Roku remote with both keyboard shortcuts and clickable on-screen buttons.

A banner at the top confirms which device you're controlling:

```
Connected: Living Room Roku (192.168.1.100)
```

A status bar at the bottom shows feedback for each action (e.g., "Sent: Up") or error messages if a command fails.

### Keyboard Shortcuts

Keyboard input is the fastest way to control your Roku. All shortcuts work regardless of which button has mouse focus.

#### Navigation

| Key | Action |
|-----|--------|
| **Arrow Up** | Navigate up |
| **Arrow Down** | Navigate down |
| **Arrow Left** | Navigate left |
| **Arrow Right** | Navigate right |
| **Enter** | Select / OK |

#### System

| Key | Action |
|-----|--------|
| **h** | Home -- return to Roku home screen |
| **b** | Back -- go back one menu level |
| **i** | Info -- show info overlay |
| **p** | Power -- toggle device power on/off |

#### Media Playback

| Key | Action |
|-----|--------|
| **Space** | Play / Pause |
| **r** | Rewind |
| **f** | Fast forward |

#### Volume

| Key | Action |
|-----|--------|
| **=** (equals) | Volume up |
| **-** (minus) | Volume down |
| **m** | Mute / unmute |

#### Favorites & Apps

| Key | Action |
|-----|--------|
| **g** | Open the apps browser to manage favorites |
| **1** - **5** | Launch favorite app in that slot |

#### Screen Navigation

| Key | Action |
|-----|--------|
| **Esc** | Return to device list |
| **q** | Quit the application |

### On-Screen Buttons

The remote control panel is organized into four sections. All buttons are clickable with the mouse.

**Power & Navigation**
- **Power** -- toggle device power (red button)
- **Home** -- return to home screen
- **Back** -- go back one level

**D-Pad**
- **Up**, **Down**, **Left**, **Right** -- directional navigation
- **OK** -- select/confirm (green button)

**Media**
- **Rev** -- rewind
- **Play/Pause** -- toggle playback
- **Fwd** -- fast forward

**Volume**
- **Vol -** -- decrease volume
- **Mute** -- toggle mute
- **Vol +** -- increase volume

---

## Favorite Apps

You can mark up to 5 installed apps as favorites for quick access. Favorites appear as numbered buttons on the Remote Screen and can be launched instantly with the **1**-**5** keys.

Each device has its own set of favorites, so your Living Room Roku and Bedroom Roku can have different shortcuts.

### Managing Favorites

1. From the Remote Screen, press **g** to open the **Apps Screen**.
2. The Apps Screen shows all installed apps on the device. Apps marked as favorites have a **\*** prefix.
3. Use the arrow keys to highlight an app, then press **f** to toggle it as a favorite.
4. Press **Enter** on any app to launch it immediately.
5. Press **r** or click **Refresh** to force-reload the app list from the device.
6. Press **Esc** to return to the Remote Screen.

The maximum number of favorites is 5. If you try to add a 6th, an error message is shown.

### Using Favorites

Once you've set up favorites, the Remote Screen shows a favorites bar between the device banner and the remote panel:

```
[1: Netflix] [2: YouTube] [3: Hulu]
```

- Press **1** through **5** to launch the corresponding favorite app.
- Click a favorite button with the mouse to launch it.
- If a slot is empty, the key press is ignored.

### App List Caching

The list of installed apps is cached for 24 hours to avoid repeated network fetches. The cache is per-device and stored alongside other device data. When the cache expires, the app list is automatically re-fetched the next time you open the Apps Screen. Press **r** on the Apps Screen to force a refresh at any time.

### Apps Screen Keybindings

| Key | Action |
|-----|--------|
| **Enter** | Launch selected app |
| **f** | Toggle favorite on selected app |
| **r** | Force-refresh app list from device |
| **Esc** | Return to Remote Screen |

---

## Persistent Storage

### Configuration Directory

Roku TUI stores device data following the XDG Base Directory Specification:

```
$XDG_CONFIG_HOME/roku-tui/devices.json
```

If `XDG_CONFIG_HOME` is not set, the default location is:

```
~/.config/roku-tui/devices.json
```

The directory is created automatically on first save.

### Saved Device Data

Each saved device records the following information:

| Field | Description |
|-------|-------------|
| **name** | Device name (e.g., "Living Room Roku") |
| **model** | Roku model (e.g., "Roku Streaming Stick 4K") |
| **serial** | Device serial number |
| **host** | IP address |
| **port** | ECP port (default 8060) |
| **subnet** | Local network subnet (e.g., 192.168.1.0/24) |
| **source_ip** | Your machine's IP used to reach the device |
| **first_seen** | When the device was first discovered |
| **last_seen** | When the device was last seen during a scan |
| **last_connected** | When you last selected the device for remote control |
| **favorites** | List of up to 5 favorite app IDs |
| **app_cache** | Cached list of installed apps with a 24-hour TTL |

Devices are identified by serial number. If the serial number is unavailable, the device is identified by its `host:port` combination instead.

### What Gets Saved and When

| Event | What happens |
|-------|-------------|
| **App starts** | Saved devices loaded from disk |
| **Network scan completes** | All discovered devices merged into storage |
| **Manual connect succeeds** | Connected device saved to storage |
| **Device selected for control** | `last_connected` timestamp updated |

If the storage file becomes corrupted, it is automatically backed up as `devices.json.bak` and a fresh file is started. Storage failures never crash the application.

---

## Troubleshooting

### Error Code Reference

When something goes wrong, the status bar displays an error with a code. Here is what each code means:

| Code | Message | What It Means |
|------|---------|---------------|
| **E1001** | Network discovery failed | SSDP multicast could not be sent. Check network connectivity. |
| **E1002** | No devices found | No Roku devices responded to the scan. |
| **E1003** | Device connection failed | Could not reach the Roku at the given IP/port. |
| **E1004** | Command failed | A keypress or launch command was rejected by the device. |
| **E1005** | Device info error | Could not retrieve device information. |
| **E1006** | Invalid response | The device sent an unexpected response. |
| **E1007** | Network timeout | The operation took too long. The device may be slow or unreachable. |
| **E1008** | Device unreachable | The Roku is not responding on the network. |
| **E1009** | Parse error | The device returned malformed data. |
| **E1010** | Socket error | A low-level network error occurred. |

### Common Issues

**No devices found during scan**

- Ensure your computer and Roku are on the same network/subnet.
- Some routers block multicast traffic between devices. Try connecting by IP instead (press **a**).
- Check that the Roku is powered on and connected to Wi-Fi.

**"Device unreachable" after selecting a saved device**

- The device's IP may have changed. Run a new scan (press **s**) to update it.
- Verify the device is powered on and connected to the network.

**Connection works but commands don't respond**

- The Roku may be in a state that doesn't accept certain commands (e.g., during firmware update).
- Try pressing **h** (Home) first to return to a known state.
- Check the status bar for error messages.

**Manual IP connection fails**

- Verify the IP address is correct. You can find it on your Roku under Settings > Network > About.
- The default port is 8060. Only specify a different port if you know your Roku uses one.
- Ensure no firewall is blocking port 8060 between your computer and the Roku.

**Saved devices not appearing**

- Check that `~/.config/roku-tui/devices.json` exists and is readable.
- If the file was corrupted, it has been backed up as `devices.json.bak`. You can inspect it to recover device data.

**Keyboard shortcuts not working on Remote Screen**

- Click somewhere on the remote control area first to ensure the window has focus.
- If the IP input field has focus, press **Esc** first, then select the device again.
