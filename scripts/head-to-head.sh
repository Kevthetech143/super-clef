#!/usr/bin/env bash
# Regenerates the Super Clef vs Super Jev head-to-head table .
#   scripts/head-to-head.sh            run both systems live (about 45 min), write the table
#   REUSE=1 scripts/head-to-head.sh    reuse saved raw results in $WORK, just rebuild the table
# Env: OUT (required, the table file), WORK (required, raw results dir),
#      EVALSET (required, the eval jsonl), JEV_ASK (live Super Jev ask.py, run read-only: replay, no auto-save).
# Rules: runs one question at a time (one clef process at a time); Super Clef state is its own.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export OUT="${OUT:?set OUT to the table file to write}"
export WORK="${WORK:?set WORK to a folder for raw results}"
export EVALSET="${EVALSET:?set EVALSET to the eval jsonl file}"
export JEV_ASK="${JEV_ASK:-$HOME/.claude/skills/super-jev/ask.py}"
export CLEF_ASK="$ROOT/skills/super-jev/ask.py"
# The Super Jev state dir (where its traces.jsonl lives); the caller names it, Super Clef never defaults to it.
export JEV_STATE_DIR="${JEV_STATE_DIR:?set JEV_STATE_DIR to the Super Jev state folder}"
export REUSE="${REUSE:-0}"
mkdir -p "$WORK"
if [ "$REUSE" != 1 ]; then node "$ROOT/bin/superclef.js" import-state --from-superjev --json >/dev/null; fi
exec python3 - <<'PY'
import json, os, re, statistics, subprocess, time, datetime
W=os.environ['WORK']; OUT=os.environ['OUT']; REUSE=os.environ['REUSE']=='1'
ASKS={'Super Jev':os.environ['JEV_ASK'],'Super Clef':os.environ['CLEF_ASK']}
EVAL=[json.loads(l) for l in open(os.environ['EVALSET'])]
# the 5-question timing set (same five as the terminal test): principal, kind, text, gold substrings, absent
TIMING=[
 dict(id='t1',principal='primary',kind='note',q='what did the near-twin tie-break change',gold=['pr-134-twin-tie-breaker'],absent=False),
 dict(id='t2',principal='primary',kind='code',q='where is the function that benches a failing pointer implemented',gold=['pr-133','test_sick_pointer_breaker'],absent=False),
 dict(id='t3',principal='primary',kind='claim',q='a pointer that fails three times in a row is benched',gold=[],absent=False),
 dict(id='t4',principal='example',kind='saved answer',q='what is the project code name',gold=['timeline.md'],absent=False),
 dict(id='t5',principal='primary',kind='absent',q='What city is the amber-heron-052 storage site in, and what is its gate code?',gold=[],absent=True),
]
def run(system, row, replay):
    env=dict(os.environ)
    if row.get('kind')=='saved answer': replay=False   # the saved-answer question is the one that must read the saved answer
    if replay: env.update(SUPERJEV_REPLAY='1',SUPERJEV_AUTO_CACHE='0',SUPERJEV_TRACES='1')
    else: env.update(SUPERJEV_AUTO_CACHE='0',SUPERJEV_TRACES='1')
    cmd=['python3',ASKS[system],'--json','--principal',row['principal']]
    q=row.get('q') or row['question']
    cmd+= ['--claim',q] if row.get('kind')=='claim' else [q]
    t=time.time(); p=subprocess.run(cmd,capture_output=True,text=True,env=env,timeout=900); secs=time.time()-t
    d={}
    for l in reversed(p.stdout.splitlines()):
        if l.startswith('{'):
            try: d=json.loads(l); break
            except Exception: pass
    calls=0
    if system=='Super Jev':
        try:
            tr=json.loads([l for l in open(os.path.join(os.path.expanduser(os.environ["JEV_STATE_DIR"]),row['principal'],"traces.jsonl")) if l.strip()][-1])
            calls=len(tr.get('routing',{}))+2 if tr.get('tier')!='cache' else 0
        except Exception: calls=0
    return dict(id=row['id'],system=system,secs=round(secs,1),exit=p.returncode,outcome=d.get('outcome'),leans_none=bool(d.get('leans_none')),
      files=[(f.get('path'),f.get('tier')) for f in d.get('files',[])[:5]],verdict=d.get('verdict') or d.get('claims') or None,
      calls=calls,raw=(p.stdout[-600:] if not d else ''))
def get(system,name,rows,replay):
    f=f"{W}/{name}-{system.replace(' ','_')}.json"
    if REUSE and os.path.exists(f): return json.load(open(f))
    res=[]
    for r in rows:
        res.append(run(system,r,replay)); json.dump(res,open(f,'w'),indent=1)
    return res
def score(rows,res):
    n=len(rows); ans=[r for r in rows if not r['absent'] and (r.get('gold') or r.get('gsub'))]; ab=[r for r in rows if r['absent']]
    by={x['id']:x for x in res}; hit=0; strict=0; leads=0
    for r in ans:
        gold=[os.path.realpath(g) for g in r.get('gold',[])]
        paths=[os.path.realpath(p) for p,_ in by[r['id']]['files']]
        if any(p in gold for p in paths) or any(s in p for p in paths for s in r.get('gsub',[])): hit+=1
    for r in ab:
        x=by[r['id']]
        if x['outcome']=='not-found' and not x['files']: strict+=1; leads+=1
        elif x['outcome']=='found' and x['leans_none'] and all(t!='confirmed' for _,t in x['files']): leads+=1
    s=[x['secs'] for x in res]
    return dict(hit=f"{hit}/{len(ans)}",nf=f"{strict}/{len(ab)}",nf2=f"{leads}/{len(ab)}",med=round(statistics.median(s),1),mx=round(max(s),1))
for t in TIMING: t['gsub']=t['gold']
tabs={}
for name,rows,replay in (('timing',TIMING,True),('eval30',EVAL,True)):
    tabs[name]={s:(rows,get(s,name,rows,replay)) for s in ASKS}
def table(name,title):
    out=[f"### {title}\n","| Measure | Super Jev | Super Clef |","|---|---|---|"]
    sc={s:score(*tabs[name][s]) for s in ASKS}
    j,c=sc['Super Jev'],sc['Super Clef']
    out+= [f"| Right file in top 5 | {j['hit']} | {c['hit']} |",
           f"| Honest not-found, strict (no files listed) | {j['nf']} | {c['nf']} |",
           f"| Honest not-found incl. leans-none leads (nothing confirmed) | {j['nf2']} | {c['nf2']} |",
           f"| Median seconds | {j['med']} | {c['med']} |",f"| Max seconds | {j['mx']} | {c['mx']} |",
           ""]
    return '\n'.join(out)
def detail(name):
    rows,_=tabs[name]['Super Jev']; out=["| id | question | Jev outcome / secs | Clef outcome / secs |","|---|---|---|---|"]
    for i,r in enumerate(rows):
        a=tabs[name]['Super Jev'][1][i]; b=tabs[name]['Super Clef'][1][i]
        out.append(f"| {r['id']} | {r['q' if 'q' in r else 'question'][:60]} | {a['outcome']} {a['secs']}s | {b['outcome']} {b['secs']}s |")
    return '\n'.join(out)
md=f"""# Super Clef vs Super Jev, head-to-head (private; generated {datetime.datetime.now().strftime('%Y-%m-%d %H:%M ET')} by scripts/head-to-head.sh)

Same connected files: Super Clef state is `superclef import-state --from-superjev` (read-only copy). Both run through ask.py --json, one question at a time, sequentially (times are wall clock, cold).
Top-5 hit = a gold file (eval jsonl: gold paths; timing set: gold name fragments) among the first 5 listed files. Super Clef lists clef "possible" leads, never certain on its own.
The eval jsonl runs with saved answers off (replay) for both; the timing set too, except t4, which is the saved-answer question and reads the saved answer (no auto-save anywhere). Timing q3 is a claim check with no gold file (see its detail row).

{table('timing','5-question timing set')}
{table('eval30','Your eval jsonl (success = gold file in top 5, or honest not-found on the absent ones)')}
### Images and video

| Measure | Super Jev | Super Clef |
|---|---|---|
| Image + video questions (connect, ask, honest not-found) | not supported (text-only judge) | Super Clef only: frozen suite `npm run test:media` (4 live cases incl. one absent) passed; 2 image + 1 video + 1 absent terminal questions all PASS, about 26 s each |

### Per-question detail: timing set
{detail('timing')}

### Per-question detail: your eval jsonl
{detail('eval30')}
"""
open(OUT,'w').write(md); print('wrote',OUT)
PY
