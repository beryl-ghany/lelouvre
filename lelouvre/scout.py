"""Read-only scouting loop with explicit rules, evidence, and durable run history.

No candidate information is sent to sources. No source text can invoke actions.
"""
from __future__ import annotations

import hashlib
import html
import json
import re
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urlsplit
from uuid import uuid4

from .store import Problem, Store, now

SOURCES = (
    {"id":"cloudflare", "name":"Cloudflare careers", "organization":"Cloudflare", "type":"internship",
     "adapter":"greenhouse", "url":"https://boards-api.greenhouse.io/v1/boards/cloudflare/jobs?content=true",
     "official_url":"https://www.cloudflare.com/careers/jobs/", "hosts":["boards-api.greenhouse.io"],
     "link_hosts":["boards.greenhouse.io","job-boards.greenhouse.io","www.cloudflare.com","www.cloudflare.com."]},
    {"id":"datadog", "name":"Datadog careers", "organization":"Datadog", "type":"internship",
     "adapter":"greenhouse", "url":"https://boards-api.greenhouse.io/v1/boards/datadog/jobs?content=true",
     "official_url":"https://careers.datadoghq.com/", "hosts":["boards-api.greenhouse.io"],
     "link_hosts":["boards.greenhouse.io","job-boards.greenhouse.io","careers.datadoghq.com"]},
    {"id":"isaca", "name":"ISACA Foundation scholarships", "organization":"ISACA Foundation", "type":"scholarship",
     "adapter":"page_watch", "url":"https://isaca.secure-platform.com/a/page/ISACAfoundation/aboutscholarships",
     "official_url":"https://www.isaca.org/about-us/isaca-foundation", "hosts":["isaca.secure-platform.com"],
     "link_hosts":["isaca.secure-platform.com"]},
    {"id":"isc2", "name":"Center for Cyber Safety and Education scholarships", "organization":"Center for Cyber Safety and Education", "type":"scholarship",
     "adapter":"page_watch", "url":"https://www.iamcybersafe.org/s/academic-scholarships",
     "official_url":"https://www.iamcybersafe.org/s/academic-scholarships", "hosts":["www.iamcybersafe.org","iamcybersafe.org"],
     "link_hosts":["www.iamcybersafe.org","iamcybersafe.org"]},
    {"id":"simplify2027", "name":"Simplify Summer 2027 internships (GitHub)", "organization":"Community internship list", "type":"internship",
     "adapter":"github_markdown", "url":"https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/README.md",
     "official_url":"https://github.com/SimplifyJobs/Summer2027-Internships",
     "hosts":["raw.githubusercontent.com"],
     "link_hosts":["boards.greenhouse.io","job-boards.greenhouse.io","jobs.lever.co","boards.eu.greenhouse.io"]},
    {"id":"reddit_internships", "name":"r/internships (community leads)", "organization":"Reddit community", "type":"internship",
     "adapter":"reddit_json", "url":"https://www.reddit.com/r/internships/new.json?limit=50",
     "official_url":"https://www.reddit.com/r/internships", "hosts":["www.reddit.com"],
     "user_agent":"Lelouvre/0.3 (personal read-only internship scout; contact: local)",
     "link_hosts":["boards.greenhouse.io","job-boards.greenhouse.io","jobs.lever.co","boards.eu.greenhouse.io"]},
    {"id":"reddit_csmajors", "name":"r/csMajors (community leads)", "organization":"Reddit community", "type":"internship",
     "adapter":"reddit_json", "url":"https://www.reddit.com/r/csMajors/search.json?q=internship+2027&restrict_sr=1&sort=new&limit=50",
     "official_url":"https://www.reddit.com/r/csMajors", "hosts":["www.reddit.com"],
     "user_agent":"Lelouvre/0.3 (personal read-only internship scout; contact: local)",
     "link_hosts":["boards.greenhouse.io","job-boards.greenhouse.io","jobs.lever.co","boards.eu.greenhouse.io"]},
)
# Direct employer feeds keep discovery useful when community sites block requests.
SOURCES += tuple({
    "id": board, "name": organization + " careers", "organization": organization,
    "type": "internship", "adapter": "greenhouse",
    "url": f"https://boards-api.greenhouse.io/v1/boards/{board}/jobs?content=true",
    "official_url": f"https://job-boards.greenhouse.io/{board}",
    "hosts": ["boards-api.greenhouse.io"],
    "link_hosts": ["boards.greenhouse.io", "job-boards.greenhouse.io", *extra],
} for board, organization, extra in (
    ("stripe", "Stripe", ["stripe.com"]),
    ("mongodb", "MongoDB", ["www.mongodb.com", "mongodb.com"]),
    ("robinhood", "Robinhood", ["careers.robinhood.com"]),
    ("duolingo", "Duolingo", ["careers.duolingo.com"]),
))
SOURCE_MAP = {source["id"]: source for source in SOURCES}
INTERVAL = 6 * 60 * 60
RULES_VERSION = 'rules-5-explicit-summer-dates'
SKILLS = {
    "Python": (r"\bpython\b", "Résumé: Campus inventory API and Python projects"),
    "Java": (r"\bjava\b", "Résumé: Campus inventory API Spring Boot backend"),
    "TypeScript": (r"\btypescript\b", "Résumé: Study group scheduler"),
    "JavaScript": (r"\bjavascript\b", "Résumé: React and web development"),
    "SQL": (r"\bsql\b|\bpostgresql\b", "Résumé: SQL and PostgreSQL"),
    "React": (r"\breact\b", "Résumé: Study group scheduler and demo web coursework"),
    "Linux": (r"\blinux\b", "Résumé: vulnerability assessment project"),
    "Docker": (r"\bdocker\b", "Résumé: isolated security environments"),
    "REST APIs": (r"\brest(?:ful)?\b", "Résumé: Campus inventory API and Study group scheduler APIs"),
    "Git": (r"\bgit\b", "Résumé: developer tools"),
    "Knowledge graphs": (r"knowledge graphs?|\bneo4j\b", "Résumé: Campus inventory API"),
}
MISSING_SKILLS = {"AWS":r"\baws\b|amazon web services", "Azure":r"\bazure\b", "Kubernetes":r"\bkubernetes\b|\bk8s\b", "IAM":r"\biam\b|identity and access management", "Go":r"\bgolang\b|\bgo programming\b", "C++":r"c\+\+", "Terraform":r"\bterraform\b"}


class TextParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.skip = 0
        self.parts = []

    def handle_starttag(self, tag, _attrs):
        if tag in ("script", "style", "noscript", "svg"):
            self.skip += 1

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript", "svg") and self.skip:
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


def plain(value):
    parser = TextParser()
    parser.feed(html.unescape(str(value)))
    return " ".join(" ".join(parser.parts).split())


def secure_url(url, hosts):
    try:
        parsed = urlsplit(url)
        return parsed.scheme == "https" and parsed.hostname in hosts and not parsed.username and not parsed.password and parsed.port in (None, 443)
    except (ValueError, TypeError):
        return False


class RestrictedRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts

    def redirect_request(self, request, response, code, message, headers, newurl):
        if not secure_url(newurl, self.hosts):
            raise ValueError("Source redirected outside its configured HTTPS hosts")
        return super().redirect_request(request, response, code, message, headers, newurl)


def fetch(source):
    if not secure_url(source["url"], source["hosts"]):
        raise ValueError("Source destination is not allowed")
    opener = urllib.request.build_opener(RestrictedRedirect(source["hosts"]))
    accept = "application/json" if source["adapter"] in ("greenhouse", "reddit_json") else "text/html"
    request = urllib.request.Request(source["url"], headers={
        "User-Agent": source.get("user_agent", "Lelouvre/0.3 (personal internship and scholarship tracker)"),
        "Accept": accept,
    })
    with opener.open(request, timeout=25) as response:
        content = response.read(12 * 1024 * 1024 + 1)
        if len(content) > 12 * 1024 * 1024:
            raise ValueError("Source response exceeded the size limit")
        return content.decode("utf-8", errors="replace")


def excerpt(text, pattern, width=90):
    match = re.search(pattern, text, re.I)
    if not match:
        return ""
    return text[max(0,match.start()-width):min(len(text),match.end()+width)]


def evaluate(title, location, description):
    """Conservative tri-state targeting; scores are priorities, never probabilities."""
    text = title + " " + description
    reasons, blockers = [], []
    if not re.search(r"\bintern(?:ship)?\b", title, re.I):
        return None
    if not re.search(r"software|security|cyber|cloud|research|infrastructure|platform|backend|full.stack|developer|site reliability", title, re.I):
        return None
    track = "Security" if re.search(r"security|cyber", title, re.I) else "Research" if re.search(r"research", title, re.I) else "SWE"
    season_pattern = r"summer\s*(?:of\s*)?2027|2027\s*(?:summer)|summer\s*\([^)]{0,80}\b2027\b[^)]{0,40}\)"
    title_other = re.search(r"summer\s*(?:of\s*)?(20\d\d)", title, re.I)
    # Explicit program date ranges prove the year; graduation dates do not.
    range_pattern = r"(?:May|June|Jun)\s+\d{1,2}(?:,?\s+2027)?\s*[-–—]\s*(?:Aug(?:ust)?|Sep(?:tember)?)\s+\d{1,2},?\s+2027"
    date_evidence = re.search(range_pattern, description, re.I) if re.search(r"summer", title, re.I) else None
    season = "confirmed" if re.search(season_pattern, text, re.I) or date_evidence else "unknown"
    target = "potential_match" if season=="confirmed" else "needs_review"
    if title_other and title_other.group(1) != "2027":
        target, season = "excluded", "other_season"
        blockers.append("The title specifies a different summer.")
    elif season=="unknown":
        blockers.append("Summer 2027 is not explicitly confirmed in the posting text.")
    else:
        reasons.append({"reason":"Summer 2027 mentioned", "excerpt":excerpt(text,season_pattern) or excerpt(text,range_pattern)})
    if re.search(r"\bsouth carolina\b|,\s*SC\b|\borangeburg\b", location, re.I):
        target="excluded"
        blockers.append("South Carolina appears in the location; review multi-location alternatives if applicable.")
    usa_pattern=r"\bunited states\b|\bUSA\b|\bU\.S\.|\bnew york\b|\bboston\b|\bseattle\b|\bsan francisco\b|\bsan jose\b|\baustin\b|\bdenver\b|\bsan mateo\b|\blos angeles\b|\bwashington,?\s*dc\b|\bchicago\b|,\s*(?:CA|NY|MA|WA|TX|CO|VA|NC|GA|PA|NJ|FL|IL)\b"
    us_location=bool(re.search(usa_pattern,location+' '+title,re.I))
    if not us_location:
        if target!='excluded': target='needs_review'
        blockers.append("US location is not confirmed by the current location rules; remote/geographic eligibility needs checking.")
        if re.search(r'\b(?:spain|france|united kingdom|UK|germany|singapore|india|canada|australia|japan|ireland|portugal|netherlands|poland)\b',location,re.I):
            target='excluded'
            blockers.append('The stated location is outside the current US search scope.')
    if re.search(r'\bph\.?d\b|\bdoctoral\b',title,re.I):
        target='excluded'
        blockers.append('The role title specifies doctoral study; the candidate is an undergraduate.')
    if re.search(r"(?:must|required).{0,35}(?:ph\.?d|doctoral)|(?:ph\.?d|doctoral).{0,35}(?:required|enrolled)",text,re.I):
        if target!='excluded': target='needs_review'
        blockers.append("Possible doctoral requirement; verify undergraduate eligibility.")
    if re.search(r"(?:must be|only|require[sd]?).{0,35}(?:u\.?s\.? citizens?|security clearance)|(?:citizenship|clearance).{0,20}required",text,re.I):
        if target!='excluded': target='needs_review'
        blockers.append("Possible citizenship/clearance restriction; eligibility is unconfirmed.")
    matched=[]
    for name,(pattern,evidence) in SKILLS.items():
        if re.search(pattern,description,re.I):
            matched.append({"skill":name,"candidate_evidence":evidence,"posting_excerpt":excerpt(description,pattern)})
    gaps=[{"skill":name,"posting_excerpt":excerpt(description,pattern),"candidate_evidence":"Not recorded in the supplied résumé"} for name,pattern in MISSING_SKILLS.items() if re.search(pattern,description,re.I)]
    coast=bool(re.search(r"new york|boston|seattle|san francisco|san jose|san mateo|los angeles|,\s*(?:CA|NY|MA|WA|VA|NJ|PA|NC)\b",location,re.I))
    if coast: reasons.append({"reason":"Preferred coast location mentioned","excerpt":location})
    # Resume evidence is explanatory only. It never gates discovery or affects priority.
    score=min(100,(70 if season=='confirmed' else 25)+(20 if coast else 0)+10)
    if target=='excluded':score=0
    return {"target":target,"season":season,"track":track,"priority":score,"reasons":reasons,"matched_skills":matched,"gaps":gaps,"blockers":blockers,"eligibility":"Needs review", "rules_version":RULES_VERSION}


def extract(source, content):
    if source["adapter"] == "github_markdown":
        from .adapters.github_markdown import extract_github_markdown
        return extract_github_markdown(source, content)
    if source["adapter"] == "reddit_json":
        from .adapters.reddit_json import extract_reddit_json
        return extract_reddit_json(source, content)
    if source["adapter"] == "greenhouse":
        payload=json.loads(content)
        if not isinstance(payload,dict) or not isinstance(payload.get("jobs"),list):
            raise ValueError("Source did not return a jobs list")
        records=[]
        for job in payload["jobs"]:
            if not isinstance(job,dict) or not job.get('id') or not isinstance(job.get('title'),str):
                raise ValueError("Source contains an invalid job record")
            title=job['title'][:500]
            description=plain(job.get('content',''))[:120000]
            location=plain((job.get('location') or {}).get('name',''))[:1000]
            office_names=[plain(office.get('name','')) for office in job.get('offices',[]) if isinstance(office,dict)]
            if office_names:location=(location+'; '+'; '.join(office_names))[:1000]
            match=evaluate(title,location,description)
            if match is None:continue
            url=job.get('absolute_url','')
            if not secure_url(url,source['link_hosts']):
                match['blockers'].append('Application link is outside the configured source domains.')
                match['target']='needs_review' if match['target']!='excluded' else 'excluded'
                url=''
            elif source.get('adapter') == 'greenhouse':
                board = source['url'].split('/boards/', 1)[1].split('/', 1)[0]
                url = f"https://job-boards.greenhouse.io/{board}/jobs/{job['id']}"
                match['verification'] = 'verified_ats'
                match['apply_platform'] = 'greenhouse'
            records.append({"external_id":str(job['id']),"title":title,"location":location,"url":url,
                "description":description,"kind":"listing","availability":"listed","evaluation":match})
        return records,len(payload['jobs'])
    description=plain(content)
    if len(description)<150 or re.search(r"^(?:just a moment|access denied|verify you are human)",description,re.I):
        raise ValueError("Page content unavailable or blocked; a browser or dedicated adapter may be needed")
    evidence=excerpt(description,r"scholarships?.{0,100}(?:open|closed|applications?)|applications?.{0,100}(?:open|closed)",200)
    return [{"external_id":"program-page","title":source['name'],"location":"Not evaluated","url":source['url'],
        "description":description[:120000],"kind":"program_page","availability":"unknown",
        "evaluation":{"target":"needs_review","season":"not_applicable","track":"Scholarship","priority":0,
            "reasons":[{"reason":"Official program page monitored; not an individually verified open award","excerpt":evidence}],
            "matched_skills":[],"gaps":[],"blockers":["Individual awards, current cycles, deadlines, and eligibility require review. Page changes do not establish that an application is open."],
            "eligibility":"Unknown","rules_version":"rules-1"}}],1


class ScoutStore:
    def __init__(self, store: Store):
        self.store=store
        with store.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS scout_sources (
                    id TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 1,
                    last_attempt TEXT, last_success TEXT, status TEXT NOT NULL DEFAULT 'not_checked', error TEXT
                );
                CREATE TABLE IF NOT EXISTS scout_settings (id INTEGER PRIMARY KEY CHECK(id=1), enabled INTEGER NOT NULL DEFAULT 0);
                INSERT OR IGNORE INTO scout_settings(id,enabled) VALUES(1,0);
                CREATE TABLE IF NOT EXISTS scout_runs (
                    id TEXT PRIMARY KEY, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT,
                    trigger TEXT NOT NULL, total_seen INTEGER NOT NULL DEFAULT 0,
                    new_count INTEGER NOT NULL DEFAULT 0, changed_count INTEGER NOT NULL DEFAULT 0,
                    successful_sources INTEGER NOT NULL DEFAULT 0, failed_sources INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS scout_checks (
                    id TEXT PRIMARY KEY, run_id TEXT NOT NULL REFERENCES scout_runs(id), source_id TEXT NOT NULL REFERENCES scout_sources(id),
                    status TEXT NOT NULL, seen INTEGER NOT NULL DEFAULT 0, saved INTEGER NOT NULL DEFAULT 0,
                    error TEXT, checked_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS opportunities (
                    id TEXT PRIMARY KEY, source_id TEXT NOT NULL REFERENCES scout_sources(id), external_id TEXT NOT NULL,
                    type TEXT NOT NULL, organization TEXT NOT NULL, title TEXT NOT NULL, location TEXT NOT NULL,
                    url TEXT NOT NULL, kind TEXT NOT NULL, availability TEXT NOT NULL,
                    first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, last_checked TEXT NOT NULL,
                    content_hash TEXT NOT NULL, description TEXT NOT NULL, evaluation TEXT NOT NULL,
                    disposition TEXT NOT NULL DEFAULT 'new', last_change TEXT NOT NULL DEFAULT 'discovered',
                    UNIQUE(source_id,external_id)
                );
                CREATE TABLE IF NOT EXISTS opportunity_snapshots (
                    id TEXT PRIMARY KEY, opportunity_id TEXT NOT NULL REFERENCES opportunities(id),
                    content_hash TEXT NOT NULL, payload TEXT NOT NULL, captured_at TEXT NOT NULL
                );
            """)
            for source in SOURCES:
                connection.execute("INSERT OR IGNORE INTO scout_sources(id) VALUES(?)",(source['id'],))
            connection.execute("INSERT OR IGNORE INTO schema_version VALUES(2)")
            # Reassess stored evidence after rules change, without refetching or
            # rewriting source snapshots, publication dates, or application state.
            for row in connection.execute("SELECT id,title,location,description,evaluation FROM opportunities WHERE kind='listing'").fetchall():
                previous=json.loads(row['evaluation'])
                if previous.get('rules_version')!=RULES_VERSION:
                    evaluation=evaluate(row['title'],row['location'],row['description'])
                    if evaluation is not None:
                        connection.execute('UPDATE opportunities SET evaluation=? WHERE id=?',(json.dumps(evaluation),row['id']))

    def status(self):
        with self.store.connect() as connection:
            configured={r['id']:dict(r) for r in connection.execute("SELECT * FROM scout_sources")}
            runs=[dict(r) for r in connection.execute("SELECT * FROM scout_runs ORDER BY started_at DESC LIMIT 12")]
            enabled=bool(connection.execute("SELECT enabled FROM scout_settings WHERE id=1").fetchone()[0])
            latest_check=connection.execute("SELECT MAX(finished_at) FROM scout_runs").fetchone()[0]
            count=connection.execute("SELECT COUNT(*) FROM opportunities WHERE disposition='new' AND json_extract(evaluation,'$.target')!='excluded'").fetchone()[0]
        return {"enabled":enabled,"interval_hours":6,"last_completed":latest_check,"unreviewed":count,
            "sources":[{**{k:s[k] for k in ('id','name','organization','type','adapter','official_url')},**configured[s['id']]} for s in SOURCES],
            "runs":runs,            "unsupported":["LinkedIn (session adapter planned)","Indeed (session adapter planned)","X","General web search","Additional employer/research sources"],
            "engine":"Evidence-based rules; optional local LLM for listing analysis only","submissions":"Prepare/review pipeline available; live submit gated","email":False}

    def list(self,scope='all',show_excluded=False):
        if scope not in ('all','internship','scholarship'):raise Problem('Unknown opportunity scope.')
        with self.store.connect() as connection:
            query="SELECT * FROM opportunities"
            rows=[dict(r) for r in connection.execute(query)]
        results=[]
        for row in rows:
            row['evaluation']=json.loads(row['evaluation'])
            if scope!='all' and row['type']!=scope:continue
            if not show_excluded and row['evaluation']['target']=='excluded':continue
            row.pop('description')
            results.append(row)
        return sorted(results,key=lambda r:(r['availability']=='not_listed',-r['evaluation']['priority'],r['first_seen']),reverse=False)

    def detail(self,opportunity_id):
        with self.store.connect() as connection:
            row=connection.execute("SELECT * FROM opportunities WHERE id=?",(opportunity_id,)).fetchone()
            if row is None:raise Problem('Opportunity not found.',404,'not_found')
            result=dict(row)
            result['evaluation']=json.loads(result['evaluation'])
            result['snapshots']=[dict(r) for r in connection.execute('SELECT id,content_hash,captured_at FROM opportunity_snapshots WHERE opportunity_id=? ORDER BY captured_at DESC',(opportunity_id,))]
            return result

    def disposition(self,opportunity_id,value):
        if value not in ('new','saved','dismissed'):raise Problem('Unknown opportunity disposition.')
        with self.store.connect() as connection:
            cursor=connection.execute('UPDATE opportunities SET disposition=? WHERE id=?',(value,opportunity_id))
            if not cursor.rowcount:raise Problem('Opportunity not found.',404,'not_found')

    def settings(self,data):
        with self.store.connect() as connection:
            if 'enabled' in data:
                if not isinstance(data['enabled'],bool):raise Problem('Enabled must be true or false.')
                connection.execute('UPDATE scout_settings SET enabled=? WHERE id=1',(int(data['enabled']),))
            if 'source_id' in data:
                if data['source_id'] not in SOURCE_MAP or not isinstance(data.get('source_enabled'),bool):raise Problem('Unknown source or invalid setting.')
                connection.execute('UPDATE scout_sources SET enabled=? WHERE id=?',(int(data['source_enabled']),data['source_id']))

    def ingest(self,source,records,run_id,total_seen):
        timestamp=now();added=changed=0
        with self.store.connect() as connection:
            connection.execute('BEGIN IMMEDIATE')
            seen=[]
            for record in records:
                external_id=record['external_id'];seen.append(external_id)
                canonical=json.dumps({k:record[k] for k in ('title','location','url','description','kind')},sort_keys=True)
                digest=hashlib.sha256(canonical.encode()).hexdigest()
                current=connection.execute('SELECT * FROM opportunities WHERE source_id=? AND external_id=?',(source['id'],external_id)).fetchone()
                if current is None:
                    added+=1;opportunity_id=uuid4().hex
                    organization=record.get('organization') or source['organization']
                    connection.execute('''INSERT INTO opportunities(id,source_id,external_id,type,organization,title,location,url,kind,availability,first_seen,last_seen,last_checked,content_hash,description,evaluation)
                        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',(opportunity_id,source['id'],external_id,source['type'],organization,record['title'],record['location'],record['url'],record['kind'],record['availability'],timestamp,timestamp,timestamp,digest,record['description'],json.dumps(record['evaluation'])))
                    connection.execute('INSERT INTO opportunity_snapshots VALUES(?,?,?,?,?)',(uuid4().hex,opportunity_id,digest,canonical,timestamp))
                else:
                    opportunity_id=current['id']
                    different=current['content_hash']!=digest
                    reopened=current['availability']=='not_listed'
                    if different or reopened:
                        changed+=1
                        connection.execute('INSERT INTO opportunity_snapshots VALUES(?,?,?,?,?)',(uuid4().hex,opportunity_id,digest,canonical,timestamp))
                    organization=record.get('organization') or source['organization']
                    connection.execute('''UPDATE opportunities SET organization=?,title=?,location=?,url=?,availability=?,last_seen=?,last_checked=?,content_hash=?,description=?,evaluation=?,
                        disposition=CASE WHEN ? THEN 'new' ELSE disposition END,last_change=CASE WHEN ? THEN 'listed_again' WHEN ? THEN 'changed' ELSE last_change END WHERE id=?''',
                        (organization,record['title'],record['location'],record['url'],record['availability'],timestamp,timestamp,digest,record['description'],json.dumps(record['evaluation']),different or reopened,reopened,different,opportunity_id))
            if source['adapter']=='greenhouse':
                # Only a complete successful feed may mark previously seen roles absent.
                for row in connection.execute('SELECT id,external_id FROM opportunities WHERE source_id=?',(source['id'],)).fetchall():
                    if row['external_id'] not in seen:
                        connection.execute("UPDATE opportunities SET availability='not_listed',last_checked=? WHERE id=?",(timestamp,row['id']))
            connection.execute("UPDATE scout_sources SET last_attempt=?,last_success=?,status='healthy',error=NULL WHERE id=?",(timestamp,timestamp,source['id']))
            connection.execute('INSERT INTO scout_checks VALUES(?,?,?,?,?,?,?,?)',(uuid4().hex,run_id,source['id'],'healthy',total_seen,len(records),None,timestamp))
        return added,changed


class ScoutAgent:
    def __init__(self,store,fetcher=fetch,trace_log=None):
        self.repository=ScoutStore(store);self.store=store;self.fetcher=fetcher;self.trace_log=trace_log
        self.lock=threading.Lock();self.stop_event=threading.Event();self.thread=None
        with store.connect() as connection:
            connection.execute("UPDATE scout_runs SET status='interrupted',finished_at=? WHERE status='running'",(now(),))

    def start(self,trigger='manual'):
        if not self.lock.acquire(blocking=False):raise Problem('A scout run is already in progress.',409,'run_active')
        run_id=uuid4().hex
        try:
            with self.store.connect() as connection:
                connection.execute('INSERT INTO scout_runs(id,status,started_at,trigger) VALUES(?,?,?,?)',(run_id,'running',now(),trigger))
            thread=threading.Thread(target=self._run,args=(run_id,),daemon=True,name='lelouvre-scout')
            thread.start()
        except Exception:
            self.lock.release();raise
        return {'id':run_id,'status':'running'}

    def _run(self,run_id):
        total=added=changed=success=failed=0
        try:
            enabled={s['id'] for s in self.repository.status()['sources'] if s['enabled']}
            for source in SOURCES:
                if self.stop_event.is_set():break
                if source['id'] not in enabled:continue
                try:
                    with self.store.connect() as connection:
                        connection.execute("UPDATE scout_sources SET last_attempt=?,status='checking',error=NULL WHERE id=?",(now(),source['id']))
                    content=self.fetcher(source)
                    records,seen=extract(source,content)
                    fresh,updated=self.repository.ingest(source,records,run_id,seen)
                    total+=seen;added+=fresh;changed+=updated;success+=1
                except Exception as error:
                    failed+=1
                    if isinstance(error,urllib.error.HTTPError):message=f'HTTP {error.code}; source unavailable'
                    elif isinstance(error,(TimeoutError,urllib.error.URLError,OSError)):message='Network access failed or timed out; previous results retained'
                    else:message=str(error)[:250] if isinstance(error,ValueError) else 'Source processing failed; previous results retained'
                    with self.store.connect() as connection:
                        connection.execute("UPDATE scout_sources SET last_attempt=?,status='failed',error=? WHERE id=?",(now(),message,source['id']))
                        connection.execute('INSERT INTO scout_checks VALUES(?,?,?,?,?,?,?,?)',(uuid4().hex,run_id,source['id'],'failed',0,0,message,now()))
            status='interrupted' if self.stop_event.is_set() else 'completed_with_errors' if failed else 'completed'
            with self.store.connect() as connection:
                connection.execute('UPDATE scout_runs SET status=?,finished_at=?,total_seen=?,new_count=?,changed_count=?,successful_sources=?,failed_sources=? WHERE id=?',
                    (status,now(),total,added,changed,success,failed,run_id))
        except Exception:
            with self.store.connect() as connection:
                connection.execute("UPDATE scout_runs SET status='failed',finished_at=? WHERE id=?",(now(),run_id))
        finally:
            try:
                from .scout_fit import enrich_new_discovery_fits
                enrich_new_discovery_fits(self.store, limit=8, trace_log=self.trace_log)
            except Exception:
                pass
            self.lock.release()

    def start_scheduler(self):
        def schedule():
            while not self.stop_event.wait(20):
                status=self.repository.status()
                last=status['last_completed']
                due=not last or time.time()-datetime.fromisoformat(last).timestamp()>=INTERVAL
                if status['enabled'] and due:
                    try:self.start('scheduled')
                    except Problem:pass
        self.thread=threading.Thread(target=schedule,daemon=True,name='lelouvre-scheduler');self.thread.start()

    def close(self):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=2)


def main():
    import argparse
    from pathlib import Path
    parser=argparse.ArgumentParser(description='Run one read-only Lelouvre scout check')
    parser.add_argument('--database',type=Path,default=Path(__file__).resolve().parent.parent/'data'/'lelouvre.sqlite3')
    parser.add_argument('--enable-schedule',action='store_true',help='Enable six-hour checks when the dashboard server is running')
    args=parser.parse_args()
    store=Store(args.database);agent=ScoutAgent(store)
    if args.enable_schedule:agent.repository.settings({'enabled':True})
    result=agent.start('command_line')
    print('Scouting configured public sources; no candidate information is sent.',flush=True)
    if not agent.lock.acquire(timeout=150):
        agent.close();raise SystemExit('Scout did not finish within the time limit; inspect run status.')
    agent.lock.release()
    status=agent.repository.status()
    run=next(run for run in status['runs'] if run['id']==result['id'])
    print(json.dumps({'run':run,'sources':[{k:s[k] for k in ('id','status','error','last_success')} for s in status['sources']]},indent=2),flush=True)
    agent.close()


if __name__=='__main__':main()
