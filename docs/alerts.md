Alerts Guide
============

The controller watches itself while it runs. When something goes wrong --
or something worth knowing happens -- it raises an **alert**. Every alert is
written to the daemon log tagged `ALERT [CRITICALITY]`, and can additionally
be delivered over MQTT or to a webhook endpoint of your choosing.

Alerts are configured on the **Alerts** panel on the Config tab of the web
interface.

The alert registry
------------------

Alerts come in three tiers, shown most critical first in the panel:

### Critical -- something is actively wrong or dangerous

| id | label | what it means |
| --- | --- | --- |
| `emergency_shutoff` | Emergency shutoff fired | The kiln shut itself down because the emergency temperature limit was exceeded. |
| `heat_rate_too_low` | Kiln not heating fast enough | The kiln fell too far behind its ramp and the run was aborted. Usually a failed element or a relay stuck open. |
| `relay_stuck_on` | Relay stuck on | Elements commanded off but temperature keeps climbing -- the relay may be welded closed. |
| `tc_failure` | Thermocouple failure | Lost thermocouple connection, a short circuit, an out-of-range cold junction, or too many read errors in a row. |
| `temp_implausible` | Implausible temperature reading | A reading jumped or flatlined in a way that suggests a failing sensor or loose wiring. |

### Warning -- the run is degraded but not lost

| id | label | what it means |
| --- | --- | --- |
| `run_aborted` | Run aborted | A firing ended early because of an error. |
| `restart_resumed` | Firing resumed after power outage | The controller restarted after an outage and resumed the run automatically. |
| `restart_not_resumed` | Run not resumed after power outage | Power was out longer than the automatic restart window, so the firing did not resume and needs attention. |
| `catch_up_stalled` | Kiln falling behind schedule | The kiln has been unable to keep up with its target temperature for an extended period. |
| `scheduled_run_missed` | Scheduled run missed | A scheduled firing could not start when its time arrived. |

### Info -- normal lifecycle worth knowing about

| id | label | what it means |
| --- | --- | --- |
| `run_started` | Run started | A firing started, whether from the button, a schedule, or the api. |
| `run_completed` | Run completed | A firing finished its schedule successfully. |
| `cooled_safe` | Kiln cooled to safe temperature | After a finished run the kiln dropped below a safe handling temperature and can be opened. |
| `controller_restarted` | Controller restarted | The controller process started up. Unexpected restarts are worth noticing. |

These ids are stable: they appear in stored settings and in delivered
payloads, so they are never renamed -- only added or retired.

Choosing which alerts fire
--------------------------

Toggle any checkbox on the Alerts panel to enable or disable that alert.
Changes are saved immediately to `storage/alerts.json` (no restart required)
and survive a reboot.

Disabling an alert silences it completely: the detector still runs, but
nothing is announced anywhere -- not in the log, and not through any
delivery service.

Repeats are rate limited. Ongoing *conditions* (like relay stuck on) re-fire
at most once every 5 minutes so a long-running problem does not flood you.
*Events* (run started/completed/aborted, power-outage restarts, missed
schedules, controller restarts) always come through immediately; they happen
once, so they are never suppressed.

Detection thresholds
--------------------

How eagerly each condition fires is tuned from `config.py`. Temperatures and
deltas are in your display scale:

| alert | setting | default |
| --- | --- | --- |
| cooled_safe | `cooled_safe_temp` | 150 -- below this the kiln is safe to open |
| relay_stuck_on | `relay_stuck_on_rise` within `relay_stuck_on_window` | 25 degree rise within 10 minutes while elements are off |
| temp_implausible | `temp_implausible_jump` | 50 -- impossible change between two readings |
| tc_failure | `tc_error_percent_limit` | 30 -- percent of failed reads per window |
| catch_up_stalled | `catch_up_stalled_minutes` | 15 -- minutes behind schedule before alerting |

Delivery
--------

Beyond the daemon log, fired alerts can be delivered two ways. Both are set
up at the bottom of the Alerts panel, take effect immediately when toggled,
and their settings persist alongside the alert checkboxes.

**MQTT** publishes each alert as json on its own topic (default
`kiln/alert`), next to the live state stream, so Home Assistant or Node-RED
can trigger notifications or automations. It uses the same broker settings
as the live state feed (`mqtt_enable`, `mqtt_host`, ... in `config.py`);
until those exist the panel shows a hint instead of failing silently.

**Webhook** posts each alert as json to any url that accepts a POST: ntfy
(`https://ntfy.sh/<your-topic>`), Discord or Slack incoming webhooks, Home
Assistant webhooks, Pushover, or your own receiver. Posts run on a
background thread with a timeout (`alert_webhook_timeout` in `config.py`,
default 10 seconds) so a slow endpoint can never stall heater control.
Failures are logged and retried never -- the next alert posts normally.

Every delivery carries the same json payload:

    {
      "source": "kiln-controller",
      "alert_id": "relay_stuck_on",
      "label": "Relay stuck on",
      "criticality": "critical",
      "context": {"rise": 31.2, "minutes": 10, "temperature": 212},
      "time": "2026-08-23T14:43:50",
      "epoch": 1787485430
    }

`alert_id` is the stable registry id from the tables above; match on it when
building automations. `context` carries whatever details the detector had
(rise amounts, minutes behind, temperatures) and varies per alert.

Storage format
--------------

`storage/alerts.json` holds both the enabled flags and the delivery
settings:

    {
      "enabled": {
          "emergency_shutoff": true,
          "run_started": false
      },
      "delivery": {
          "mqtt_enabled": false,
          "mqtt_topic": "kiln/alert",
          "webhook_enabled": false,
          "webhook_url": ""
      }
    }

Older files were just the enabled map with no wrapper; those load unchanged
and are rewritten in the new format the next time anything is saved. Unknown
alert ids in the file are kept so a downgrade does not silently re-enable
something, and corrupt values fall back to their defaults.

Api
---

The panel talks to `/api/alerts`; see [api.md](api.md) for the exact calls.
In short: GET returns the registry plus delivery settings, POST accepts an
`enabled` map and/or a `delivery` map, validates everything up front, and
never partially saves a bad request.
