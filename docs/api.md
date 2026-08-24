start a run

    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

skip the first part of a run
restart the kiln on a specific profile and start at minute 60

    curl -d '{"cmd":"run", "profile":"cone-05-long-bisque","startat":60}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

stop a schedule

    curl -d '{"cmd":"stop"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

post a memo

    curl -d '{"cmd":"memo", "memo":"some significant message"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

stats for currently running schedule

    curl -X GET http://0.0.0.0:8081/api/stats

list the alert registry with enabled flags and delivery settings, ordered most critical first

    curl -X GET http://0.0.0.0:8081/api/alerts

enable or disable alerts (any subset)

    curl -d '{"enabled": {"relay_stuck_on": true, "run_started": false}}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api/alerts

update alert delivery settings (any subset; see [alerts.md](alerts.md))

    curl -d '{"delivery": {"webhook_enabled": true, "webhook_url": "https://ntfy.sh/my-kiln", "mqtt_enabled": true, "mqtt_topic": "kiln/alert"}}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api/alerts

pause a run (maintain current temperature until resume)

    curl -d '{"cmd":"pause"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

resume a paused run
    
    curl -d '{"cmd":"resume"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

schedule a firing to start at a future date and time. start_time can be
a unix epoch or an ISO 8601 string. returns the id of the scheduled run

    curl -d '{"cmd":"schedule", "profile":"cone-05-long-bisque", "start_time":"2026-08-12T05:00"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

schedule a firing and skip the first 120 minutes of the schedule

    curl -d '{"cmd":"schedule", "profile":"cone-05-long-bisque", "start_time":"2026-08-12T05:00", "startat":120}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

list scheduled runs

    curl -d '{"cmd":"list_schedules"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api

cancel a scheduled run

    curl -d '{"cmd":"cancel_schedule", "id":"abc12345"}' -H "Content-Type: application/json" -X POST http://0.0.0.0:8081/api
