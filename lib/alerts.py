import datetime
import json
import logging
import os
import threading
import time

import config

log = logging.getLogger(__name__)

# criticality tiers, highest first. the web ui renders alerts in this
# order so the most dangerous conditions are at the top of the panel.
CRITICAL = 'critical'
WARNING = 'warning'
INFO = 'info'

CRITICALITY_ORDER = [CRITICAL, WARNING, INFO]

# the alert registry. order matters: it must be sorted by criticality
# descending, then in a stable review order within each tier.
#
# ids are part of the stored settings file and eventually of notification
# payloads - never rename one, only add or retire.
ALERTS = [
    # ---- critical: something is actively wrong or dangerous ----------
    {
        'id': 'emergency_shutoff',
        'label': 'Emergency shutoff fired',
        'description': 'The kiln shut itself down because the emergency temperature limit was exceeded.',
        'criticality': CRITICAL,
    },
    {
        'id': 'heat_rate_too_low',
        'label': 'Kiln not heating fast enough',
        'description': 'The kiln fell too far behind its ramp and the run was aborted. Usually a failed element or a relay stuck open.',
        'criticality': CRITICAL,
    },
    {
        'id': 'relay_stuck_on',
        'label': 'Relay stuck on',
        'description': 'The elements are commanded off but the temperature keeps climbing, which means the relay may be welded closed.',
        'criticality': CRITICAL,
    },
    {
        'id': 'tc_failure',
        'label': 'Thermocouple failure',
        'description': 'Lost connection to the thermocouple, a short circuit, an out-of-range cold junction, or too many read errors in a row.',
        'criticality': CRITICAL,
    },
    {
        'id': 'temp_implausible',
        'label': 'Implausible temperature reading',
        'description': 'A reading jumped or flatlined in a way that suggests a failing sensor or loose wiring.',
        'criticality': CRITICAL,
    },
    # ---- warning: the run is degraded but not lost --------------------
    {
        'id': 'run_aborted',
        'label': 'Run aborted',
        'description': 'A firing ended early because of an error.',
        'criticality': WARNING,
    },
    {
        'id': 'restart_resumed',
        'label': 'Firing resumed after power outage',
        'description': 'The controller restarted after an outage and resumed the run automatically.',
        'criticality': WARNING,
    },
    {
        'id': 'restart_not_resumed',
        'label': 'Run not resumed after power outage',
        'description': 'Power was out longer than the automatic restart window, so the firing did not resume and needs attention.',
        'criticality': WARNING,
    },
    {
        'id': 'catch_up_stalled',
        'label': 'Kiln falling behind schedule',
        'description': 'The kiln has been unable to keep up with its target temperature for an extended period.',
        'criticality': WARNING,
    },
    {
        'id': 'scheduled_run_missed',
        'label': 'Scheduled run missed',
        'description': 'A scheduled firing could not start when its time arrived.',
        'criticality': WARNING,
    },
    # ---- info: normal lifecycle worth knowing about -------------------
    {
        'id': 'run_started',
        'label': 'Run started',
        'description': 'A firing started, whether from the button, a schedule, or the api.',
        'criticality': INFO,
    },
    {
        'id': 'run_completed',
        'label': 'Run completed',
        'description': 'A firing finished its schedule successfully.',
        'criticality': INFO,
    },
    {
        'id': 'cooled_safe',
        'label': 'Kiln cooled to safe temperature',
        'description': 'After a finished run the kiln dropped below a safe handling temperature and can be opened.',
        'criticality': INFO,
    },
    {
        'id': 'controller_restarted',
        'label': 'Controller restarted',
        'description': 'The controller process started up. Unexpected restarts are worth noticing.',
        'criticality': INFO,
    },
]

# where fired alerts go beyond the log. these are the web-editable
# delivery settings (Alerts panel, config tab); they persist in the
# same state file as the enabled flags and take effect immediately.
DEFAULT_DELIVERY = {
    'mqtt_enabled': False,
    'mqtt_topic': 'kiln/alert',
    'webhook_enabled': False,
    'webhook_url': '',
}

DELIVERY_STRING_KEYS = ('mqtt_topic', 'webhook_url')
DELIVERY_BOOL_KEYS = ('mqtt_enabled', 'webhook_enabled')


def validate_delivery(updates, strict=True):
    '''clean up a partial delivery settings map from the web api.
    returns (clean_updates, ignored_keys). unknown keys and wrong types
    are dropped silently unless strict, in which case a ValueError with
    a client-friendly message is raised instead.'''
    clean = {}
    ignored = []
    for key, value in updates.items():
        if key in DELIVERY_BOOL_KEYS:
            if isinstance(value, bool):
                clean[key] = value
            elif strict:
                raise ValueError("%s must be true or false" % key)
        elif key in DELIVERY_STRING_KEYS:
            if not isinstance(value, str):
                raise ValueError("%s must be a string" % key)
            value = value.strip()
            if key == 'mqtt_topic' and not value:
                raise ValueError("mqtt_topic cannot be empty")
            if key == 'webhook_url' and value and \
                    not value.lower().startswith(('http://', 'https://')):
                raise ValueError(
                    "webhook_url must start with http:// or https://")
            clean[key] = value
        else:
            ignored.append(key)
            if strict:
                raise ValueError("unknown delivery setting: %s" % key)
    return clean, ignored


class AlertStore(object):
    '''persists alert enabled flags and delivery settings to a json
    file so they survive a reboot.

    file schema:
        {"enabled":  {<alert_id>: <bool>, ...},
         "delivery": {"mqtt_enabled": bool, "mqtt_topic": str,
                      "webhook_enabled": bool, "webhook_url": str}}

    older files were the bare enabled map; those load unchanged and are
    rewritten in the new format on the next save.'''

    def __init__(self, state_file=None):
        self.state_file = state_file or config.alerts_state_file
        self.lock = threading.Lock()
        self.enabled = {a['id']: True for a in ALERTS}
        self.delivery = dict(DEFAULT_DELIVERY)
        self.load()

    def load(self):
        '''read enabled/disabled flags and delivery settings from disk.
        unknown ids in the file are kept so downgrades do not silently
        re-enable things; missing ids stay at their default (enabled).
        corrupt or malformed values fall back to defaults.'''
        try:
            with open(self.state_file) as infile:
                saved = json.load(infile)
        except (IOError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        enabled_updates = saved.get('enabled')
        if not isinstance(enabled_updates, dict):
            # legacy format: the whole file is the enabled map
            enabled_updates = {k: v for k, v in saved.items()
                               if k not in ('enabled', 'delivery')}
        for key, value in enabled_updates.items():
            if isinstance(value, bool):
                self.enabled[key] = value
        delivery_updates = saved.get('delivery')
        if isinstance(delivery_updates, dict):
            clean, _ = validate_delivery(delivery_updates,
                                         strict=False)
            self.delivery.update(clean)

    def save(self):
        '''write flags and settings to disk so they survive a reboot'''
        dirname = os.path.dirname(self.state_file)
        if dirname and not os.path.isdir(dirname):
            os.makedirs(dirname)
        with open(self.state_file, 'w') as outfile:
            json.dump({'enabled': self.enabled,
                       'delivery': self.delivery},
                      outfile, indent=4, sort_keys=True, ensure_ascii=False)

    def definitions(self):
        '''the full registry with current enabled flags, already ordered
        by criticality descending'''
        return [{
            'id': a['id'],
            'label': a['label'],
            'description': a['description'],
            'criticality': a['criticality'],
            'enabled': self.enabled.get(a['id'], True),
        } for a in ALERTS]

    def delivery_settings(self):
        '''a copy of the current delivery settings'''
        return dict(self.delivery)

    def set_delivery(self, updates):
        '''merge validated delivery updates and persist. returns an
        error string, or None on success.'''
        try:
            clean, _ = validate_delivery(updates)
        except ValueError as e:
            return str(e)
        with self.lock:
            self.delivery.update(clean)
            self.save()
        log.info("alert delivery updated: %s" % clean)
        return None

    def set_enabled(self, alert_id, value):
        '''enable/disable one alert. returns False if the id is unknown.'''
        with self.lock:
            if alert_id not in self.enabled:
                return False
            if self.enabled[alert_id] == bool(value):
                return True
            self.enabled[alert_id] = bool(value)
            self.save()
        log.info("alert %s %s" % (alert_id, 'enabled' if value else 'disabled'))
        return True


# lookup table for emission-time metadata
ALERT_DEFS = {a['id']: a for a in ALERTS}

# lifecycle events that happen at most once per run or per process.
# they bypass cooldown so nothing can suppress them; every other alert
# is a repeating condition and gets rate limited.
EVENT_ALERTS = {
    'run_started',
    'run_completed',
    'run_aborted',
    'restart_resumed',
    'restart_not_resumed',
    'scheduled_run_missed',
    'controller_restarted',
}


class LogSink(object):
    '''default sink: logs every emitted alert. notification services
    (push, email, chat) plug in here as additional sinks later.'''

    def __init__(self):
        self.log = logging.getLogger('alerts')

    def deliver(self, alert_id, label, criticality, context):
        detail = json.dumps(context, sort_keys=True) if context else ''
        self.log.warning("ALERT [%s] %s: %s %s",
                         criticality.upper(), label, alert_id, detail)


class AlertManager(object):
    '''central alert emission point. checks each condition against the
    enabled flags chosen on the web ui, rate limits repeating conditions,
    and fans out to sinks. detection code calls emit() and does not need
    to know whether any delivery service exists.'''

    def __init__(self, store=None, condition_cooldown=300):
        self.store = store or AlertStore()
        self.sinks = []
        self.condition_cooldown = condition_cooldown
        self._last_emit = {}
        self.lock = threading.Lock()

    def add_sink(self, sink):
        self.sinks.append(sink)

    def emit(self, alert_id, context=None):
        '''emit an alert by registry id. returns True if it was delivered
        to any sink, False if suppressed (disabled, rate limited, or an
        unknown id).'''
        definition = ALERT_DEFS.get(alert_id)
        if definition is None:
            log.error("alert id '%s' is not in the registry" % alert_id)
            return False

        if not self.store.enabled.get(alert_id, True):
            log.debug("alert %s suppressed: disabled in the web ui" % alert_id)
            return False

        if alert_id not in EVENT_ALERTS:
            with self.lock:
                now = time.monotonic()
                last = self._last_emit.get(alert_id)
                if last is not None and now - last < self.condition_cooldown:
                    log.debug("alert %s suppressed: cooling down" % alert_id)
                    return False
                self._last_emit[alert_id] = now

        delivered = False
        payload = context or {}
        for sink in list(self.sinks):
            try:
                sink.deliver(alert_id, definition['label'],
                             definition['criticality'], payload)
                delivered = True
            except Exception as e:
                log.error("alert sink %s failed for %s: %s"
                          % (sink, alert_id, e))
        return delivered


def alert_payload(alert_id, label, criticality, context):
    '''the json body every delivery sink sends. alert ids are stable
    registry ids (never renamed), so consumers can match on them.'''
    now = time.time()
    return {
        'source': 'kiln-controller',
        'alert_id': alert_id,
        'label': label,
        'criticality': criticality,
        'context': context or {},
        'time': datetime.datetime.fromtimestamp(now).isoformat(timespec='seconds'),
        'epoch': int(now),
    }


class WebhookSink(object):
    '''posts alert payloads as json to any url: ntfy, discord, slack and
    home assistant webhooks, the pushover api, or your own receiver.

    delivery happens on a throwaway daemon thread so a slow or dead
    endpoint can never stall heater control or the web server event
    loop. reads its settings live from the AlertStore, so changes made
    on the web ui take effect immediately.'''

    def __init__(self, store, timeout=None, async_deliver=True, poster=None):
        self.store = store
        self.timeout = timeout
        self.async_deliver = async_deliver
        self.poster = poster or self._requests_post

    def deliver(self, alert_id, label, criticality, context):
        settings = self.store.delivery
        if not settings.get('webhook_enabled'):
            return
        url = (settings.get('webhook_url') or '').strip()
        if not url:
            log.debug("webhook sink has no url configured, skipping %s"
                      % alert_id)
            return
        payload = alert_payload(alert_id, label, criticality, context)
        if self.async_deliver:
            worker = threading.Thread(target=self._post,
                                      args=(url, payload), daemon=True)
            worker.start()
        else:
            self._post(url, payload)

    def _post(self, url, payload):
        try:
            response = self.poster(url, payload, self.timeout)
            status = getattr(response, 'status_code', 0)
            if status >= 300:
                log.error("alert webhook post to %s failed: HTTP %s %s"
                          % (url, status,
                             getattr(response, 'text', '')[:200]))
            else:
                log.info("alert %s posted to webhook" % payload['alert_id'])
        except Exception as e:
            log.error("alert webhook post to %s failed: %s" % (url, e))

    def _requests_post(self, url, payload, timeout):
        import requests
        return requests.post(url, json=payload,
                             timeout=timeout or config.alert_webhook_timeout)


class MqttSink(object):
    '''publishes alert payloads to the mqtt broker as json, on a topic
    of their own so subscribers can tell alerts from the live state.

    the client is built off-thread (a first delivery before it connects
    is skipped) and rebuilt when the topic changes on the web ui.
    publishes only happen when mqtt_enabled is on in the delivery
    settings AND the broker itself is enabled in config.py.'''

    def __init__(self, store, out_cls=None):
        self.store = store
        self.out_cls = out_cls
        self.out = None
        self.built_topic = None
        self.building = False

    def deliver(self, alert_id, label, criticality, context):
        settings = self.store.delivery
        if not settings.get('mqtt_enabled'):
            return
        topic = settings.get('mqtt_topic') or DEFAULT_DELIVERY['mqtt_topic']
        if self.out is None or self.built_topic != topic:
            self.rebuild_async(topic)
            if self.out is None or self.built_topic != topic:
                # client still connecting (or connect failed); skip this
                # one rather than risk blocking heater control
                return
        self.out.publish(alert_payload(alert_id, label, criticality, context))

    def rebuild_async(self, topic):
        '''(re)build the mqtt client on a background thread so a slow
        broker can never stall whoever emitted the alert'''
        if self.building:
            return
        self.building = True

        def build():
            try:
                out_cls = self.out_cls
                if out_cls is None:
                    from mqttout import MqttOut
                    out_cls = MqttOut
                self.out = out_cls(topic=topic)
                self.built_topic = topic
                log.info("alert mqtt sink ready on topic '%s'" % topic)
            except Exception as e:
                self.out = None
                self.built_topic = None
                log.error("could not build alert mqtt sink: %s" % e)
            finally:
                self.building = False

        threading.Thread(target=build, daemon=True).start()
