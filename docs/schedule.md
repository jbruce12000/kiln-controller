Scheduling a Kiln Run
=====================

Our lives are busy. Sometimes you'll want your kiln to start at a scheduled time. The web interface and api both support scheduling a firing to start at a specific date and time.

Scheduled runs are saved to `storage/schedules.json` so they survive a reboot. The `kiln-controller.py` process must be running at the scheduled time for the run to start. The scheduler checks the schedule every `schedule_poll_interval` seconds.

## Web Interface

On the **Profiles** tab, click the **Schedule** button next to any saved schedule, pick a date and time (or use the quick offset buttons), and confirm. You can also schedule the currently selected schedule from the Overview tab. Scheduled runs are listed below the saved schedules where they can be cancelled.

## Api

Schedule a firing of a profile at a specific time. `start_time` can be a unix epoch or an ISO 8601 string.

    curl -d '{"cmd":"schedule", "profile":"cone-05-long-bisque", "start_time":"2026-08-12T05:00"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Schedule a firing and skip the first two hours [120 minutes] of the schedule (e.g. candling):

    curl -d '{"cmd":"schedule", "profile":"cone-05-long-bisque", "start_time":"2026-08-12T05:00", "startat":120}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

List scheduled runs:

    curl -d '{"cmd":"list_schedules"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

Cancel a scheduled run (use the id from list_schedules):

    curl -d '{"cmd":"cancel_schedule", "id":"abc12345"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

## Notes

A scheduled run will not start while the oven is busy. In that case it is marked **Skipped** in the scheduled runs list so it does not fire later. If the oven is idle when a scheduled time arrives, the run starts immediately.

