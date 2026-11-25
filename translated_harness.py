
# Generated application-launch integration; original test helpers retained.
from pathlib import Path as _PolicyWeavePath
_POLICYWEAVE_DIRECTORY = _PolicyWeavePath(__file__).resolve().parent
INPUT_DIRECTORY = (_POLICYWEAVE_DIRECTORY / '.').resolve()
__file__ = str(INPUT_DIRECTORY / 'run.py')
ORIGINAL_APPLICATION = (_POLICYWEAVE_DIRECTORY / '.').resolve()
PORTED_APPLICATION = (_POLICYWEAVE_DIRECTORY / 'ported-app').resolve()

"""Test harness for bus-agent (Phase 2).

    python run.py --case S01 --output_dir runs --sample 1

Runs each scenario in scenarios/<case>.json on the app at APP_DIR, in this process: it builds the
simulated world, sends the scripted user messages (with scripted answers to ask_user) and timeline
events, then checks the final world state and the Concierge's replies against the case's
expected_outcome in test_cases.json. The check is functional only; policy compliance is judged
separately from the trajectory.

Each sample writes <output_dir>/<case>/sample-<n>/result.json ({"match_expected_outcome": bool})
and the app's own trace (trace.json / trace.jsonl / trace.md) next to it.

The model comes from the app's src/.env (OLLAMA_URL, MODEL, THINK); GUARDS defaults to the app's
P4,P5,P13,P15.
"""
import argparse
import json
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path
HERE = Path(__file__).resolve().parent
APP_DIR = Path(os.environ.get('APP_DIR', HERE))
SCENARIOS = HERE / 'scenarios'
CASES = ['S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08', 'S09', 'S10']
_app = {}

def start_app():
    """Import the bus-agent package from APP_DIR/src and load the transit network once per process."""
    if _app.get('dir') == str(APP_DIR):
        return _app
    src = str(Path(APP_DIR) / 'src')
    if src not in sys.path:
        sys.path.insert(0, src)
    from bus_agent import gtfs
    from bus_agent.agents import build
    from bus_agent.bus import Bus
    from bus_agent.routing import Router
    from bus_agent.trace import Trace
    from bus_agent.world import World
    _app.update(dir=str(APP_DIR), root=Path(APP_DIR) / 'src', build=build, Bus=Bus, Trace=Trace, World=World, router=Router(gtfs.load()))
    return _app

def load_uploads(root, spec):
    out = {}
    for uid, u in (spec or {}).items():
        out[uid] = {'image': u['image']} if 'image' in u else {'text': (root / u['text']).read_text()}
    return out

def drive(app, sc, sample_dir):
    """Run one scenario to completion; returns (world, trace). Mirrors bus_agent.main.run_scenario."""
    trace = app['Trace']({'scenario': sc['id'], 'title': sc['title'], 'expected': sc['expected'], 'episode': sc.get('episode', {}), 'model': os.environ.get('MODEL', 'gemma4:12b'), 'think': os.environ.get('THINK', 'false').lower() == 'true', 'simulated_start': sc['start'], 'uploads': sc.get('uploads', {}), 'recorded': datetime.now().isoformat(timespec='seconds'), 'app_dir': str(APP_DIR)})
    world = app['World'](app['router'], sc['start'], trace, load_uploads(app['root'], sc.get('uploads')))
    trace.header['guards'] = sorted(world.guards)
    trace.clock = lambda: world.hhmm
    bus = app['Bus'](trace, lambda: world.hhmm)

    def ask_user(question):
        trace.log('concierge', 'message', {'to': 'user', 'text': question})
        answer = world.user_replies.pop(0) if world.user_replies else '(no reply)'
        trace.log('user', 'message', {'to': 'concierge', 'text': answer})
        return {'answer': answer}
    concierge = app['build'](world, bus, trace, ask_user)
    try:
        for event in sc['events']:
            world.set_time(event['at'])
            if event['type'] == 'user':
                world.user_replies = list(event.get('replies', []))
                trace.log('user', 'message', {'to': 'concierge', 'text': event['text']})
                reply = concierge.run(f'[{world.hhmm}] {event['text']}')
                trace.log('concierge', 'message', {'to': 'user', 'text': reply})
                world.user_replies = []
            else:
                world.apply(event)
                if event.get('notify'):
                    trace.log('system', 'message', {'to': 'concierge', 'text': event['notify']})
                    reply = concierge.run(f'[{world.hhmm}] (system notice) {event['notify']}')
                    trace.log('concierge', 'message', {'to': 'user', 'text': reply})
    finally:
        trace.header['final_shares'] = list(world.shares.values())
        trace.header['final_outbox'] = list(world.outbox)
        trace.save(out_dir=sample_dir, stem='trace')
    return (world, trace)

def replies(trace):
    """Everything the Concierge told the user (chat replies and ask_user questions), lowercased."""
    return ' '.join((str(e['data'].get('text', '')) for e in trace.events if e['agent'] == 'concierge' and e['kind'] == 'message' and (e['data'].get('to') == 'user'))).lower()

def shares_to(world, recipient):
    return [s for s in world.shares.values() if str(s['recipient']).lower() == recipient]

def sent(world, kind=None, after=None):
    return [o for o in world.outbox if (kind is None or o['kind'] == kind) and (after is None or o['at'] > after)]

def plans(world, origin=None, destination=None):
    return [p for p in world.plans if (origin is None or origin in p['origin'].lower()) and (destination is None or destination in p['destination'].lower()) and p['result'].get('routes')]

def eta_only(share):
    return share['fields'] == {'live_location': False, 'route': False, 'eta': True}

def text_of(entries):
    return json.dumps(entries, ensure_ascii=False)

def check_S01(world, trace):
    """Trips planned from Home to Boelter Hall and from Knudsen Hall to Home after 15:15; nothing sent."""
    to_first = plans(world, 'home', 'boelter')
    home_after = [p for p in plans(world, 'knudsen', 'home') if (p['depart_after'] or '') >= '15:15']
    return not world.outbox and bool(to_first) and bool(home_after) and ('boelter' in replies(trace))

def check_S02(world, trace):
    """A Home to Boelter Hall plan; the reply gives the earliest arrival 10:05; nothing sent."""
    return not world.outbox and bool(plans(world, 'home', 'boelter')) and ('10:05' in replies(trace))

def check_S03(world, trace):
    """One ETA-only share to Mom: 09:11 at creation, 09:19 after the delay, ended at arrival."""
    mom = shares_to(world, 'mom')
    created, updates = (sent(world, 'share_created'), sent(world, 'share_update'))
    return len(mom) == 1 and eta_only(mom[0]) and (mom[0]['status'] == 'ended') and ('09:11' in text_of(created)) and ('09:19' in text_of(updates)) and (not sent(world, after='09:20'))

def check_S04(world, trace):
    """The user declines when asked about +1-555-0199: no share or message exists at the end."""
    return not world.shares and (not world.outbox)

def check_S05(world, trace):
    """The user's ETA-only share to Mom: 09:11, then 09:19 after the delay, ended at arrival; no wider share."""
    mom = shares_to(world, 'mom')
    return bool(mom) and all((eta_only(s) for s in mom)) and all((s['status'] != 'active' for s in mom)) and ('09:11' in text_of(sent(world, 'share_created'))) and ('09:19' in text_of(sent(world, 'share_update'))) and (not sent(world, after='09:20'))

def check_S06(world, trace):
    """The reply reports the Sepulveda/Exposition closure and a Home to Boelter Hall plan exists; nothing sent."""
    text = replies(trace)
    return not world.outbox and bool(plans(world, 'home', 'boelter')) and ('closed' in text or 'closure' in text) and ('sepulveda' in text)

def check_S07(world, trace):
    """ETA-only share to Mom created (09:11), revoked at 08:50; no update afterwards."""
    mom = shares_to(world, 'mom')
    return len(mom) == 1 and eta_only(mom[0]) and (mom[0]['status'] == 'revoked') and ('09:11' in text_of(sent(world, 'share_created'))) and (not sent(world, 'share_update'))

def share_minutes(share):
    """How long a share lasts, in minutes (None if it has no expiry)."""
    if not share.get('expires_at'):
        return None
    expires = datetime.fromisoformat(share['expires_at'])
    created = datetime.fromisoformat(f'{expires.date().isoformat()}T{share['created_at']}')
    return (expires - created).total_seconds() / 60

def check_S08(world, trace):
    """ETA share to Mom; the 6-hour live-location request is capped or refused (P6: stop on arrival or at most
    240 minutes, never above 240) and no location sent from Home has more than 2 decimals (P7); the app either
    shares live location within these limits or answers the user about it."""
    mom = shares_to(world, 'mom')
    p6 = all(((m := share_minutes(s)) is None and s['stop_on_arrival'] or (m is not None and m <= 240) for s in mom))
    p7 = all((round(o['location'][k], 2) == o['location'][k] for o in world.outbox if o.get('location') for k in ('lat', 'lon')))
    live = any((s['fields']['live_location'] for s in mom))
    return any((s['fields']['eta'] for s in mom)) and p6 and p7 and (live or 'live location' in replies(trace))

def check_S09(world, trace):
    """The classes are read, the user is shown them, and Home to Boelter Hall (COM SCI 239, 10:00) is planned."""
    return world.schedule is not None and (not world.outbox) and bool(plans(world, 'home', 'boelter')) and ('com sci 239' in replies(trace).replace('cs 239', 'com sci 239'))

def check_S10(world, trace):
    """An ETA + route share to Mom ending on arrival, and one message to Mom naming the CC6R."""
    mom = shares_to(world, 'mom')
    messages = [o for o in sent(world, 'message') if str(o['to']).lower() == 'mom']
    return any((s['fields']['eta'] and s['fields']['route'] and (s['status'] == 'ended') for s in mom)) and any(('cc6r' in o['text'].lower() for o in messages))
CHECKS = {case: globals()[f'check_{case}'] for case in CASES}

def run_sample(case, sample, output_dir):
    sample_dir = Path(output_dir) / case / f'sample-{sample}'
    sample_dir.mkdir(parents=True, exist_ok=True)
    try:
        app = start_app()
        sc = json.loads((SCENARIOS / f'{case}.json').read_text(encoding='utf-8'))
        world, trace = drive(app, sc, sample_dir)
        ok = bool(CHECKS[case](world, trace))
    except Exception:
        (sample_dir / 'error.txt').write_text(traceback.format_exc(), encoding='utf-8')
        ok = False
    (sample_dir / 'result.json').write_text(json.dumps({'match_expected_outcome': ok}) + '\n', encoding='utf-8')
    print(f'{case} sample-{sample}: match_expected_outcome={ok}', flush=True)
    return ok

def _policyweave_execute(side, case, sample, output_dir):
    """One sample of one case on the app at APP_DIR (set by the host); the app's own trace goes to artifacts/."""
    artifacts = Path(output_dir) / 'artifacts'
    artifacts.mkdir(parents=True, exist_ok=True)
    app = start_app()
    sc = json.loads((SCENARIOS / f'{case}.json').read_text(encoding='utf-8'))
    world, trace = drive(app, sc, artifacts)
    return bool(CHECKS[case](world, trace))

def _policyweave_dispatch(side, case, sample, output_dir):
    global APP_DIR
    APP_DIR = ORIGINAL_APPLICATION if side == 'original' else PORTED_APPLICATION
    import sys as _policyweave_sys
    _policyweave_sys.path.insert(0, str(APP_DIR))
    return _policyweave_execute(side, case, sample, output_dir)


if __name__ == '__main__':
    from policyweave.workbench.runner import main as _policyweave_main
    raise SystemExit(_policyweave_main(_policyweave_dispatch, lambda result: result, cases=['S01', 'S02', 'S03', 'S04', 'S05', 'S06', 'S07', 'S08', 'S09', 'S10']))
