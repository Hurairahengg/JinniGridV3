# JinniGrid

Distributed MT5 trading fleet. Locked strategy: NY HMA-21 F14 double-slope on 8pt Renko.

- **Mother** — dashboard + coordinator + validator (never trades)
- **VM** — autonomous trader (never coordinates)

---

## Mother setup

Fill in mother/config.json and mother/configs/vm1.json (templates in the repo).

    cd mother/
    pip install -r ../requirements.txt
    python main.py

Dashboard: http://<mother-ip>:8080

---

## VM setup

Each VM needs MT5 running and logged in.

Copy the vm/ folder to the VM. Create vm/.env:

    MOTHER_HOST=192.168.2.105
    MOTHER_PORT=8765
    VM_ID=vm1
    SHARED_SECRET=jinni_grid_secret2347890

Then:

    cd vm/
    pip install -r ../requirements.txt
    python main.py

VM auto-connects to mother, receives its config, warms up, and trades during the NY session.

---

## Ports

- 8080 — dashboard
- 8765 — fleet WebSocket

Open both on mother's firewall.

---

## Dashboard shortcuts

- 1-9 : switch views
- Cmd/Ctrl+K : universal search
- T : cycle theme
- \ : toggle nav rail
- Esc : close panel

---

## Notes

- Strategy parameters are LOCKED in vm/strategy.py. Not editable via config.
- VM_ID in .env must match a config filename in mother/configs/<vm_id>.json.
- SHARED_SECRET in vm/.env must match shared_secret in mother/config.json.
- Mother stores everything in mother/state/fleet.db (SQLite).
