# Feature gap analysis (vs. top kiln manufacturers)

Status: research only, not yet implemented. Saved 2026-08-12.

## Current kiln-controller feature set (confirmed in code)

- Ramp/hold profiles as raw segment lists (ramp rate, target temp, hold minutes)
- Delay start (scheduler with `startat`)
- Skip-to-point / resume mid-schedule (`startat` + seek logic)
- Pause / resume
- Emergency shutoff: temp too high, too many TC errors, heat-rate-too-low
- Auto-restart after power loss (`allow_seek=False`)
- Cost estimate (`kwh_rate`)
- Auto-tuner (`kiln-tuner.py`), PID tuning docs
- Web-configurable alert selection (Alerts panel on the Config tab)
- Thermocouple diagnostics (MAX31855/MAX31856 error mapping)
- Config editor (simulate mode, TC offset, emergency limits, etc.)

## Missing features vs. top manufacturers

| Feature | Where it exists | Notes / effort |
|---|---|---|
| **Cone-Fire mode** | Skutt KilnMaster, Paragon Sentry | User enters cone # + speed + hold; controller computes the schedule. Software-only. Largest gap. |
| **Preheat / candling** | Skutt KilnMaster | Dedicated low-temp soak step; only hand-buildable via raw segments today. |
| **Temperature alarm** | Skutt, Bartlett V6, L&L | Alert (configurable per-condition on the Config tab) when target temp or end-of-firing reached. |
| **Firing / maintenance counter** | Skutt, Paragon | Persist run count per profile/config to track element wear; surface in UI. |
| **Element burnout / amperage diagnostics** | L&L DynaTrol, Paragon | Per-zone current sensor + diagnostic routine. Requires new hardware. |
| **Multi-zone thermocouples** | L&L DynaTrol (3-zone) | Multiple TC display/safety. Requires extra TC board. |
| **Cooling-rate control** | L&L DynaTrol ("Vary-Fire") | Controlled ramp-down instead of passive cooling. |
| **Rate of climb display** | L&L DynaTrol | Live deg/hr vs. target in overview UI. |
| **Program / control lock** | Nabertherm TopPilot | Prevent Stop/Pause interruption until unlocked or timer expires. |
| **Vent / AOP control** | Skutt | Automated downdraft vent relay control. Requires new relay. |

## Priority (software-only, no new hardware)

1. Cone-fire mode
2. Temperature alarm
3. Firing counter
4. Rate-of-climb display
5. Program lock

Hardware-gated (deferred): amperage/current sensing, multi-zone TC, vent control.
