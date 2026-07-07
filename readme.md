# JinniGrid V4

Distributed MT5 trading fleet with a **mother-as-brain** architecture.

The mother process owns the strategy, validates signals, and coordinates execution across VM workers. Each VM receives orders and executes trades without running its own independent strategy.

## Architecture

- **Mother** connects to its own MT5 instance (OANDA) for canonical tick data.
- **Mother** runs the single strategy and generates trade signals.
- **Mother** broadcasts signals to all VMs over WebSocket.
- **VMs** act as execution arms: receive signals, execute trades, and report position state.
- **VMs** poll their own MT5 periodically and report status back to mother.
- This design avoids per-VM strategy divergence from broker tick differences.

## Requirements

- Python dependencies: `pip install -r requirements.txt`
- MetaTrader 5 installed on both mother and VM machines
- Mother must have an OANDA MT5 account logged in for clean tick data

## Mother setup

1. Install dependencies:

```bash
pip install -r requirements.txt
```

2. Start the mother service:

```bash
cd mother
python main.py
```

3. Open the dashboard in a browser:

```text
http://<mother-ip>:8080
```

## VM setup

Each VM must have MetaTrader 5 running with its broker account.

Create `vm/.env` with the following values:

```text
MOTHER_HOST=192.168.2.105
MOTHER_PORT=8765
VM_ID=vm1
SHARED_SECRET=jinni_grid_secret2347890
```

Then start the VM process:

```bash
cd vm
python main.py
```

## Ports

- `8080` — mother dashboard HTTP
- `8765` — fleet WebSocket server

## Configuration notes

- `mother/config.json` contains mother settings, ports, and the shared secret.
- `mother/configs/<vm_id>.json` contains per-VM settings.
- `VM_ID` in `vm/.env` must match the VM config filename under `mother/configs/`.
- `SHARED_SECRET` in `vm/.env` must match `shared_secret` in `mother/config.json`.
- Mother stores fleet state in `mother/state/fleet.db`.
- Strategy logic is locked in `mother/core/strategy_brain.py`.

## Recommended workflow

1. Start the mother process first.
2. Verify the dashboard is available.
3. Start each VM after the mother is running.
4. Monitor VM connectivity and trade execution from the dashboard.

## Important

- Keep `mother/config.json` and `vm/.env` secure.
- Do not commit sensitive credentials to a public repository.
