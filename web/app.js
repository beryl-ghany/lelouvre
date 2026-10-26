'use strict';
(() => {
  const main = document.getElementById('main');
  const feedback = document.getElementById('feedback');
  (() => {
    const params = new URLSearchParams(location.search);
    const fromUrl = params.get('access_token');
    if (fromUrl) {
      try { sessionStorage.setItem('lelouvre-access-token', fromUrl); } catch {}
      params.delete('access_token');
      const next = `${location.pathname}${params.toString() ? '?' + params : ''}${location.hash}`;
      history.replaceState(null, '', next);
    }
  })();
  const token = (() => {
    try {
      const stored = sessionStorage.getItem('lelouvre-access-token');
      if (stored) return stored;
    } catch {}
    return document.querySelector('meta[name="lelouvre-token"]')?.content || '';
  })();
  const state = {
    scope: 'all', apps: [], tasks: [], config: null, detail: null, search: '', stageFilter: '',
    busy: false, agent: null, applyAgent: null, applicationRuns: [], opportunities: [],
    opportunity: null, showExcluded: false, today: null, prepareRun: null, internshipAgent: null,
    evidence: null,
  };
  const esc = v => String(v ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const typeLabel = t => t === 'scholarship' ? 'Scholarship' : 'Internship';
  const badge = (text, tone = '') => `<span class="status ${tone}">${esc(text)}</span>`;
  const heading = (title, sub) => `<h1>${esc(title)}</h1>${sub ? `<p class="muted">${esc(sub)}</p>` : ''}`;
  const button = (label, action, extra = '') => `<button type="button" data-action="${action}" ${extra}>${label}</button>`;
  const link = (label, hash, primary = false) => `<a class="button ${primary ? 'primary' : ''}" href="#${hash}">${esc(label)}</a>`;
  const scoped = rows => rows.filter(a => state.scope === 'all' || a.type === state.scope);
  const today = () => new Intl.DateTimeFormat('en-CA', { timeZone: 'America/New_York', year: 'numeric', month: '2-digit', day: '2-digit' }).format(new Date());
  let loadVersion = 0, draft = {}, createKey = crypto.randomUUID();
  try {
    draft = JSON.parse(sessionStorage.getItem('lelouvre-draft') || '{}');
    createKey = sessionStorage.getItem('lelouvre-save-key') || createKey;
  } catch {}
  function saveDraft() {
    try {
      sessionStorage.setItem('lelouvre-draft', JSON.stringify(draft));
      sessionStorage.setItem('lelouvre-save-key', createKey);
    } catch {}
  }
  function notify(message, error = false) {
    feedback.textContent = message;
    feedback.dataset.error = String(error);
  }
  async function api(path, options = {}) {
    const response = await fetch(path, {
      ...options,
      headers: {
        ...(token ? { 'X-Lelouvre-Token': token } : {}),
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
    });
    const result = await response.json();
    if (!response.ok) {
      const error = new Error(result.error || 'Request failed.');
      error.data = result;
      error.status = response.status;
      throw error;
    }
    return result;
  }
  const post = (path, data, headers = {}) => api(path, { method: 'POST', body: JSON.stringify(data), headers });

  const ROUTE_ALIASES = {
    home: 'today', opportunities: 'discover', opportunity: 'discover', settings: 'profile',
    'apply-agent': 'activity', log: 'applications',
  };

  function route() {
    const raw = (location.hash.slice(1) || 'today').split('/');
    const page = ROUTE_ALIASES[raw[0]] || raw[0];
    if (page === 'discover' && raw[0] === 'opportunity') return ['discover', raw[1]];
    return [page, raw[1]];
  }

  function navUI(page) {
    const top = page.split('/')[0];
    document.querySelectorAll('.sidebar-nav a[data-nav]').forEach(a => {
      if (a.dataset.nav === top || (top === 'prepare' && a.dataset.nav === 'discover') || (top === 'interview' && a.dataset.nav === 'applications')) {
        a.setAttribute('aria-current', 'page');
      } else a.removeAttribute('aria-current');
    });
    document.querySelectorAll('#scope [data-scope]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.scope === state.scope)));
  }

  async function refresh(extra = []) {
    const [apps, tasks, agent] = await Promise.all([api('/api/applications'), api('/api/tasks'), api('/api/agent')]);
    state.apps = apps;
    state.tasks = tasks;
    state.agent = agent;
    if (extra.includes('apply')) {
      const [applyAgent, runs] = await Promise.all([api('/api/apply-agent'), api('/api/application-runs')]);
      state.applyAgent = applyAgent;
      state.applicationRuns = runs;
    }
    if (extra.includes('activity')) {
      try { state.traces = await api('/api/traces'); } catch { state.traces = []; }
    }
    if (extra.includes('profile')) {
      state.evidence = await api('/api/evidence');
    }
    if (extra.includes('today')) {
      state.today = await api('/api/today');
      try {
        state.internshipAgent = await api('/api/internship-agent');
      } catch {
        state.internshipAgent = { enabled: false, auto_save: true, auto_apply: false, runs: [], message: 'Internship agent unavailable — restart the server.' };
      }
    }
  }

  const stamp = value => value ? new Intl.DateTimeFormat('en-US', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'America/New_York' }).format(new Date(value)) : 'Never';
  function tone(stage) { return ['Applied', 'Submitted'].includes(stage) ? 'success' : ['Rejected', 'Not selected', 'Withdrawn'].includes(stage) ? '' : 'info'; }

  function tasksHTML(tasks) {
    return tasks.map(t => {
      const overdue = t.due_date && t.due_date < today(), color = overdue ? 'urgent' : t.priority;
      return `<article class="task"><div class="row between"><div>${badge(overdue ? 'Overdue' : { urgent: 'Urgent', review: 'Needs review', info: 'Upcoming', neutral: 'Task' }[t.priority], color)}<h3>${esc(t.title)}</h3><p class="small muted">${t.organization ? esc(t.organization) : 'General'}${t.due_date ? ' · Due ' + esc(t.due_date) : ''}</p></div><div class="row">${t.application_id ? link('Open', 'application/' + t.application_id) : ''}${button('Done', 'resolve', `data-id="${t.id}"`)}</div></div></article>`;
    }).join('') || '<p class="empty">Nothing here yet.</p>';
  }

  function taskForm(applicationId = '') {
    return `<form id="task-form" class="task-form"><input type="hidden" name="application_id" value="${esc(applicationId)}"><label>Task title *<input name="title" required maxlength="200"></label><div class="form-grid"><label>Due date<input type="date" name="due_date"></label><label>Priority<select name="priority"><option value="review">Needs review</option><option value="urgent">Urgent</option><option value="info">Upcoming</option><option value="neutral">Neutral</option></select></label></div><button type="submit">Add task</button></form>`;
  }

  function todayView() {
    const t = state.today || { needs_you: [], new_roles: [], waiting: [], empty_hint: '' };
    const needs = (t.needs_you || []).map(item => {
      const dest = item.opportunity_id ? link('Continue', 'prepare/' + item.opportunity_id, true) : item.application_id ? link('Open', 'application/' + item.application_id) : '';
      const openUrl = item.url ? (item.url.startsWith('http') || item.url.startsWith('/') ? item.url : '') : '';
      const openBtn = openUrl ? `<a class="button primary" href="${esc(openUrl)}" target="_blank" rel="noopener">Open application</a>` : '';
      const msg = item.message ? `<pre class="handoff-message">${esc(item.message)}</pre>` : '';
      return `<article class="panel focus handoff-card"><h3>${esc(item.organization || 'Application')}${item.title ? ' · ' + esc(item.title) : ''}</h3>${msg}<p><strong>${esc(item.next_step || 'Your next step')}</strong></p><div class="row">${openBtn}${dest}</div></article>`;
    }).join('') || `<p class="muted">${esc(t.empty_hint || 'Nothing waiting on you.')}</p>`;
    const demoBtn = state.config?.capabilities?.demo_mode
      ? `<div class="row">${button('Run demo form (stops at sponsorship)', 'demo-form-run')}</div>` : '';
    const roles = (t.new_roles || []).map(r =>
      `<article class="opp-card"><h3>${esc(r.organization)}</h3><p>${esc(r.title)}${r.location ? ' · ' + esc(r.location) : ''}</p><p class="small">${r.fit_source === 'gemma' ? badge('Gemma fit', 'info') + ' ' : ''}${esc(r.fit_reason || '')}</p><div class="row">${button('Save', 'opportunity-disposition', `data-value="saved" data-id="${r.id}"`)}${button('Skip', 'opportunity-disposition', `data-value="dismissed" data-id="${r.id}"`)}${link('Details', 'discover/' + r.id)}</div></article>`
    ).join('') || '<p class="muted">No new roles yet. Use Find new roles below.</p>';
    const waiting = (t.waiting || []).map(w =>
      `<article class="panel"><p><strong>${esc(w.organization)}</strong> · ${esc(w.title)}</p><p class="small">Applied ${esc(w.submitted_date || '—')}${w.days_since != null ? ` · ${w.days_since} days` : ''} · ${esc(w.stage)}</p>${link('Open', 'application/' + w.id)}</article>`
    ).join('') || '<p class="muted">No applications waiting for a response yet.</p>';
    const od = t.overnight_digest || {};
    const odMeta = od.gemma_meta || {};
    const overnight = od.summary
      ? `<section class="panel focus"><h2>While you were away</h2><p>${esc(od.summary)}</p><p class="small muted">${esc(od.source === 'gemma' ? 'Summary by local Gemma · ' + (od.model || '') + (odMeta.latency_ms != null ? ' · ' + odMeta.latency_ms + ' ms' : '') : 'Offline summary')}</p></section>`
      : '';
    main.innerHTML = heading('Today', 'What needs you, what\'s new, and what you\'re waiting on.')
      + overnight
      + `<div class="hero-action">${button('Find new roles', 'internship-agent-run', 'class="primary"')}${demoBtn}</div>`
      + `<section><h2>Needs you</h2>${needs}</section>`
      + `<section><h2>New roles for you</h2><div class="card-grid">${roles}</div></section>`
      + `<section><h2>Waiting to hear back</h2>${waiting}</section>`;
  }

  function opportunityCards() {
    const rows = state.opportunities.filter(o => state.scope === 'all' || o.type === state.scope);
    return rows.map(o => `<article class="opp-card">${badge(typeLabel(o.type))}${badge(o.disposition === 'new' ? 'New' : o.disposition)}<h3>${esc(o.organization)}</h3><p>${esc(o.title)}</p><p class="small muted">${esc(o.location)}</p><div class="row">${link('Evidence', 'discover/' + o.id)}${link('Prepare', 'prepare/' + o.id)}</div></article>`).join('')
      || '<p class="empty">No opportunities yet. Run a discover check in Settings & Activity.</p>';
  }

  function discoverList() {
    main.innerHTML = heading('Discover', 'Internships, research, and scholarships with source evidence.')
      + `<div class="row between">${link('Settings & Activity', 'activity')}${button(state.showExcluded ? 'Hide excluded' : 'Include excluded', 'excluded-toggle')}</div>`
      + `<div class="card-grid opportunity-grid">${opportunityCards()}</div>`;
  }

  function discoverDetail() {
    const o = state.opportunity, e = o.evaluation;
    main.innerHTML = heading(o.title, o.organization + ' · ' + typeLabel(o.type))
      + `<div class="row">${badge(e.target, 'review')}${badge(o.availability)}${e.verification === 'verified_ats' ? badge('Verified ATS', 'success') : badge('Verify URL', 'review')}</div>`
      + `<p>${esc(o.location)}</p>${o.url ? `<p><a href="${esc(o.url)}" target="_blank" rel="noopener">Open listing ↗</a></p>` : ''}`
      + (e.gemma_fit?.blurb ? `<section class="panel"><h2>Gemma fit (local)</h2><p>${esc(e.gemma_fit.blurb)}</p>${e.gemma_fit.meta?.latency_ms != null ? `<p class="small muted">${e.gemma_fit.meta.latency_ms} ms · ${esc(e.gemma_fit.meta.model || '')}</p>` : ''}</section>` : '')
      + `<div class="cols"><section><h2>Why it surfaced</h2>${e.reasons.map(r => `<div class="panel"><h3>${esc(r.reason)}</h3><p>${esc(r.excerpt)}</p></div>`).join('') || '<p class="muted">No reasons recorded.</p>'}`
      + `<h2>Skills with résumé evidence</h2>${e.matched_skills.map(m => `<p><strong>${esc(m.skill)}</strong> — ${esc(m.posting_excerpt)}</p>`).join('') || '<p class="muted">None flagged.</p>'}`
      + `<h2>Gaps</h2>${e.gaps.map(g => `<p><strong>${esc(g.skill)}</strong></p>`).join('') || '<p class="muted">None flagged.</p>'}</section>`
      + `<section class="panel"><h3>Blockers</h3>${e.blockers.map(b => `<p>${esc(b)}</p>`).join('')}`
      + `<div class="row">${button('Save', 'opportunity-disposition', 'data-value="saved"')}${link('Prepare', 'prepare/' + o.id, true)}${button('Dismiss', 'opportunity-disposition', 'data-value="dismissed"')}</div></section></div>`
      + `<details class="quiet"><summary>Source text</summary><p class="source-text">${esc(o.description)}</p></details>`
      + `<div class="actions">${link('Back to Discover', 'discover')}</div>`;
  }

  function prepareStepper(step) {
    const labels = ['Fit check', 'Tailor documents', 'Your review', 'Ready to apply'];
    return `<div class="stepper">${labels.map((label, i) => `<div class="step ${i + 1 < step ? 'done' : i + 1 === step ? 'active' : ''}">${i + 1}. ${label}</div>`).join('')}</div>`;
  }

  function prepareView() {
    const o = state.opportunity, e = o.evaluation, run = state.prepareRun;
    const tailored = run?.packet?.tailored?.tailored || run?.packet?.tailored || {};
    const diff = tailored.diff || [];
    const resume = tailored.resume || {};
    const letter = tailored.cover_letter || {};
    const handoff = run?.handoff || run?.packet?.handoff;
    const step = !run ? 1 : !run.packet?.approved ? 3 : run.outcome === 'submitted' ? 4 : 3;
    const diffHtml = diff.map(d => `<li class="${d.kind}">${d.kind === 'add' ? '+' : '−'} ${esc(d.text)} <span class="small muted">(${esc(d.evidence_id || '')})</span></li>`).join('') || '<li>No changes from master resume.</li>';
    const failures = run?.packet?.tailored?.verification_failures || [];
    main.innerHTML = heading('Get this application ready', o.organization + ' — ' + o.title)
      + prepareStepper(step)
      + `<div class="prepare-layout"><section>`
      + `<div class="panel"><h2>Why this role</h2><p>${esc(e.matched_skills?.slice(0, 3).map(m => m.skill).join(', ') || 'Matches your target track')}.</p></div>`
      + (run ? (() => { const tp = run.packet?.tailored || {}; const gm = tp.gemma_meta || {}; return `<div class="panel"><h2>Tailored resume</h2>${tp.tailor_source ? `<p class="hint">Bullets from ${esc(tp.tailor_source)}${gm.latency_ms != null ? ' · ' + gm.latency_ms + ' ms' : ''}${gm.model ? ' · ' + esc(gm.model) : ''}</p>` : ''}<ul>${(resume.bullets || []).map(b => `<li>${esc(b.text)}${b.evidence_id ? ` <span class="small muted">← ${esc(b.evidence_id)}</span>` : ''}</li>`).join('')}</ul><h2>Cover letter</h2>${(letter.paragraphs || []).map(p => `<p>${esc(p)}</p>`).join('')}<h2>Changes from master</h2><ul>${diffHtml}</ul>${failures.length ? `<p class="hint">Before approving: ${esc(failures[0].message)}</p>` : ''}</div>`; })() : '<p class="muted">Build your tailored documents first.</p>')
      + (run?.packet?.fields?.length ? `<form id="answers-form" data-run="${esc(run.id)}" class="panel"><h2>Application answers</h2><p class="hint">Check these answers before approving. Your selected resume file is attached as-is; the tailored bullet suggestions above do not change that file.</p>${run.packet.fields.filter(f => !['hidden','submit','button'].includes(f.type)).map(f => {
        const answer = run.packet.answers?.[f.name] || '';
        if (['file','input_file'].includes(f.type)) return `<p><strong>${esc(f.label || f.name)}</strong>: ${esc(answer || 'Add your resume path in My Profile, then prepare again.')}</p>`;
        const opts = f.options || [];
        const multi = f.multiple || f.type === 'multi_value_multi_select' || f.type === 'select-multiple';
        return `<label>${esc(f.label || f.name)}${f.required ? ' *' : ''}${opts.length ? `<select name="${esc(f.name)}" ${multi ? 'multiple' : ''}><option value="">Choose / leave unanswered</option>${opts.map(o => `<option value="${esc(o.value)}" ${(Array.isArray(answer) ? answer : [String(answer)]).includes(String(o.value)) ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>` : `<textarea name="${esc(f.name)}">${esc(answer)}</textarea>`}</label>`;
      }).join('')}<button type="submit">Save reviewed answers</button></form>` : '')
      + (handoff ? `<div class="panel"><h2>Status</h2><p>${esc(handoff.headline || '')}</p><p>${esc(handoff.why || '')}</p><p><strong>${esc(handoff.what_to_do || '')}</strong></p></div>` : '')
      + `</section><aside class="prepare-panel panel"><h3>Actions</h3><div class="row">${button('Get this application ready', 'opportunity-prepare', 'class="primary"')}`
      + `${run && !run.packet?.approved && !failures.length ? button('Approve changes', 'packet-approve', `data-id="${run.id}" class="primary"`) : ''}`
      + `${run?.packet?.approved ? button('Submit for me', 'apply-execute', `data-id="${run.id}"`) : ''}`
      + `${run?.destination ? `<a class="button" href="${esc(run.destination)}" target="_blank" rel="noopener">Open application ↗</a>` : ''}`
      + `<p class="hint">Default is Ask me first. Turn on Auto-when-safe in Settings & Activity.</p></aside></div>`
      + `<div class="actions">${link('Discover', 'discover')}${link('Today', 'today')}</div>`;
  }

  function profileView() {
    const p = state.config.profile, c = state.config.capabilities;
    const ev = state.evidence || { entries: [], screening_answers: [], master_resume: {} };
    const entries = ev.entries.map(en => `<article class="panel"><h3>${esc(en.title)}</h3><p class="small">${esc(en.organization)} · ${esc(en.kind)}</p><p>${esc(en.summary)}</p><p class="hint">${(en.tools || []).join(', ')}</p></article>`).join('');
    const screening = ev.screening_answers.map(s => `<p><strong>${esc(s.question_shape)}</strong>: ${esc(s.answer)} (${s.mode === 'auto_ok' ? 'Auto-OK' : 'Always ask'})</p>`).join('');
    main.innerHTML = heading('My Profile', 'Evidence bank — every claim in your applications comes from here.')
      + `<form id="profile-form" class="panel"><h2>Application details</h2><div class="cols">${[['first_name','First name'],['last_name','Last name'],['name','Full legal name'],['email','Email'],['phone','Phone'],['school','School'],['graduation','Graduation'],['gpa','GPA'],['work_authorized','Authorized to work in the US'],['requires_sponsorship','Requires sponsorship'],['resume_path','Resume file — full PDF or DOCX path']].map(([key,label]) => `<label>${label}<input name="${key}" value="${esc(p[key] || '')}"></label>`).join('')}</div><p class="hint">Saving changes requires another packet review. Employer-specific authorization questions still appear for your review.</p><button type="submit" class="primary">Save application details</button></form>`
      + `<div class="cols"><section class="panel"><h3>${esc(p.name)}</h3><p>${esc(p.school)} · Graduation ${esc(p.graduation)}</p><h3>Screening answers</h3>${screening}<p class="hint">Work authorization: ${esc(p.authorization_answer)} · Sponsorship: ${esc(p.sponsorship_answer)}</p></section>`
      + `<section><h2>Projects & results</h2>${entries || '<p class="muted">No evidence entries yet.</p>'}<p class="hint">Model: ${esc(c.llm_model)} (open-weight via Ollama)</p></section></div>`;
  }

  function tableRows() {
    const rows = scoped(state.apps).filter(a => (!state.stageFilter || a.stage === state.stageFilter) && `${a.organization} ${a.title} ${a.cycle}`.toLowerCase().includes(state.search.toLowerCase()));
    return rows.map(a => `<tr><td><h3>${esc(a.organization)}</h3><div>${esc(a.title)}</div></td><td>${badge(a.stage, tone(a.stage))}</td><td>${esc(a.submitted_date || '—')}</td><td>${link('Open', 'application/' + a.id)}${a.stage === 'Interview' ? ' · ' + link('Prep', 'interview/' + a.id) : ''}</td></tr>`).join('')
      || '<tr><td colspan="4"><div class="empty">No applications yet.</div></td></tr>';
  }

  function applicationsView() {
    const stages = [...new Set(scoped(state.apps).map(a => a.stage))];
    if (!stages.includes(state.stageFilter)) state.stageFilter = '';
    main.innerHTML = heading('Applications', 'Pipeline, history, and next steps.')
      + `<div class="row between">${button('+ Log application', 'open-log', 'class="primary"')}<a class="button" href="/api/export.csv?scope=${state.scope}" download>Export CSV</a></div>`
      + `<div class="toolbar row"><label>Search<input id="search" value="${esc(state.search)}"></label><label>Stage<select id="stage-filter"><option value="">All</option>${stages.map(s => `<option ${s === state.stageFilter ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></label></div>`
      + `<table class="table"><thead><tr><th>Role</th><th>Stage</th><th>Submitted</th><th></th></tr></thead><tbody id="application-rows">${tableRows()}</tbody></table>`
      + `<details class="quiet"><summary>Log a past application</summary>${logFormInner()}</details>`;
  }

  function logFormInner() {
    const d = draft, kind = d.type || (state.scope === 'scholarship' ? 'scholarship' : 'internship');
    return `<form id="application-form"><label>Type<select name="type" id="application-type"><option value="internship">Internship</option><option value="scholarship">Scholarship</option></select></label><label>Organization *<input name="organization" required value="${esc(d.organization)}"></label><label>Title *<input name="title" required value="${esc(d.title)}"></label><label>Cycle<input name="cycle" value="${esc(d.cycle)}"></label><label>Submitted<input name="submitted_date" type="date" value="${esc(d.submitted_date)}"></label><label>Stage<select name="stage">${state.config.stages[kind].map(s => `<option>${esc(s)}</option>`).join('')}</select></label><button type="submit">Save</button><div id="duplicate-panel"></div></form>`;
  }

  function eventHTML(event) {
    const p = event.payload;
    let summary = event.kind;
    if (event.kind === 'updated') summary = `${p.before.stage} → ${p.after.stage}: ${p.reason}`;
    if (event.kind === 'note') summary = p.text;
    return `<article><p class="small muted">${stamp(event.created_at)}</p><p>${esc(summary)}</p></article>`;
  }

  function applicationDetail() {
    const a = state.detail;
    main.innerHTML = heading(a.organization, a.title)
      + `<div class="row">${badge(a.stage, tone(a.stage))}${link('Interview prep', 'interview/' + a.id)}</div>`
      + `<div class="cols"><section><h2>History</h2><div class="timeline">${[...a.events].reverse().map(eventHTML).join('')}</div><form id="note-form"><label>Note<textarea name="note" required maxlength="4000"></textarea></label><button type="submit">Add</button></form></section>`
      + `<section class="panel"><form id="update-form"><label>Stage<select name="stage">${state.config.stages[a.type].map(s => `<option ${s === a.stage ? 'selected' : ''}>${esc(s)}</option>`).join('')}</select></label><label>Submitted<input name="submitted_date" type="date" value="${esc(a.submitted_date)}"></label><label>Reason *<textarea name="reason" required></textarea></label><button type="submit">Update</button></form></section></div>`
      + `<div class="actions">${link('Applications', 'applications')}</div>`;
  }

  function interviewView() {
    const a = state.detail;
    const questions = ['Walk me through a project from your résumé that fits this role.', 'Why this team and this internship cycle?', 'Describe a technical challenge you solved recently.', 'What would you want to learn in the first 30 days?'];
    main.innerHTML = heading('Interview prep', a.organization + ' · ' + a.title)
      + `<div class="cols"><section class="panel"><h2>Posting & materials</h2>${a.url ? `<p><a href="${esc(a.url)}" target="_blank" rel="noopener">Saved application link ↗</a></p>` : '<p class="muted">No link saved — add one on the application record.</p>'}<p>Stage: ${badge(a.stage, 'info')}</p><p class="hint">Ground answers in projects you actually built (Study group scheduler, Campus inventory API, security work).</p></section>`
      + `<section><h2>Practice questions</h2>${questions.map(q => `<article class="panel"><p>${esc(q)}</p></article>`).join('')}</section></div>`
      + `<div class="actions">${link('Application', 'application/' + a.id)}</div>`;
  }

  function traceMeta(detail) {
    const m = (detail && detail.gemma_meta) || {};
    const bits = [];
    if (m.latency_ms != null) bits.push(m.latency_ms + ' ms');
    if (m.completion_tokens != null) bits.push(m.completion_tokens + ' out tok');
    if (m.prompt_tokens != null) bits.push(m.prompt_tokens + ' in tok');
    return bits.join(' · ');
  }

  function activityView() {
    const a = state.agent, ap = state.applyAgent || { runs: [], auto_prepare: false, auto_execute: false, browser_submit: false, queued_saved: 0, browser_available: false, execution_hosts: [], policy: '' };
    const g = state.config?.capabilities?.gemma || {};
    const traces = (state.traces || []).slice(0, 8);
    const gemmaReply = state.gemmaPing?.content ? `<p class="panel">${esc(state.gemmaPing.content)}</p><p class="small muted">${traceMeta({ gemma_meta: state.gemmaPing.gemma_meta })}</p>` : '';
    const running = a.runs.some(r => r.status === 'running'), pipeRunning = (ap.runs || []).some(r => r.status === 'running');
    main.innerHTML = heading('Settings & Activity', 'Source health, scouting, and preparation pipeline.')
      + `<section class="panel"><h2>Local Gemma</h2><p>${g.available ? badge('Ollama reachable', 'success') : badge('Gemma offline', 'review')} · Model: ${esc(g.model || '—')}${g.model_ready ? '' : ' (run ollama pull)'}</p><p class="small muted">${esc(g.base_url || '')}</p><div class="row">${button('Ping Gemma', 'gemma-ping', g.available && g.model_ready ? '' : 'disabled')}</div>${gemmaReply}</section>`
      + (traces.length ? `<section><h2>Recent Gemma traces</h2><p class="small muted"><a href="/api/traces" target="_blank" rel="noopener">JSON feed</a> · filter: <code>?kind=gemma_tailor</code></p>${traces.map(t => `<article class="panel small"><p><strong>${esc(t.kind)}</strong> · ${stamp(t.created_at)}${traceMeta(t.detail) ? ' · ' + esc(traceMeta(t.detail)) : ''}</p><pre class="handoff-message">${esc(JSON.stringify(t.detail, null, 0).slice(0, 400))}</pre></article>`).join('')}</section>` : '<section><h2>Recent Gemma traces</h2><p class="muted">Prepare a role or ping Gemma to populate traces.</p></section>')
      + `<section><h2>Discover sources</h2><div class="row">${button(running ? 'Checking…' : 'Run discover check', 'scout-run', `class="primary" ${running ? 'disabled' : ''}`)}${button(a.enabled ? 'Pause schedule' : 'Enable 6h schedule', 'scout-toggle')}</div><p class="hint">${esc(a.engine)} · Last: ${stamp(a.last_completed)}</p>`
      + a.sources.map(s => `<article class="task"><div class="row between"><div><h3>${esc(s.name)}</h3>${badge(s.status, s.status === 'healthy' ? 'success' : 'review')}${s.error ? `<p class="small">${esc(s.error)}</p>` : ''}</div>${button(s.enabled ? 'Pause' : 'Enable', 'source-toggle', `data-id="${s.id}" data-enable="${!s.enabled}"`)}</div></article>`).join('')
      + `<p class="muted">${a.unsupported.map(esc).join(' · ')}</p></section>`
      + `<section><h2>Preparation pipeline</h2><div class="row">${button(pipeRunning ? 'Running…' : 'Prepare saved roles', 'apply-run', `${pipeRunning ? 'disabled' : ''}`)}</div>`
      + `<article class="task"><div class="row between"><span>Auto-prepare saved</span>${button(ap.auto_prepare ? 'On' : 'Off', 'apply-setting', `data-key="auto_prepare" data-value="${!ap.auto_prepare}"`)}</div></article>`
      + `<article class="task"><div class="row between"><span>Auto-execute (strict gates)</span>${button(ap.auto_execute ? 'On' : 'Off', 'apply-setting', `data-key="auto_execute" data-value="${!ap.auto_execute}"`)}</div></article>`
      + `<article class="task"><div class="row between"><span>Browser submit</span>${button(ap.browser_submit ? 'On' : 'Off', 'apply-setting', `data-key="browser_submit" data-value="${!ap.browser_submit}"`)}</div></article>`
      + `<article class="task"><div class="row between"><span>Apply mode</span>${button(ap.apply_mode === 'auto_when_safe' ? 'Auto-when-safe' : 'Ask me first', 'apply-setting', `data-key="apply_mode" data-value="${ap.apply_mode === 'auto_when_safe' ? 'ask' : 'auto_when_safe'}"`)}</div></article>`
      + `<p class="hint">${esc(ap.policy)}</p></section>`;
  }

  async function load() {
    const version = ++loadVersion;
    let [page, id] = route();
    notify('');
    navUI(page);
    try {
      if (!state.config) state.config = await api('/api/state');
      if (state.config.capabilities.read_only_preview) notify('Read-only preview · Fictional data · Run locally for Gemma and application preparation.');
      const extra = [];
      if (['today', 'activity', 'prepare'].includes(page) || page === 'discover') extra.push('apply');
      if (page === 'today') extra.push('today');
      if (page === 'activity') extra.push('activity');
      if (page === 'profile') extra.push('profile');
      await refresh(extra);
      if (page === 'today' && !state.today) state.today = await api('/api/today');

      state.detail = page === 'application' || page === 'interview' ? await api('/api/applications/' + encodeURIComponent(id)) : null;
      state.opportunity = (page === 'discover' || page === 'prepare') && id ? await api('/api/opportunities/' + encodeURIComponent(id)) : null;
      if (page === 'discover' && !id) state.opportunities = await api('/api/opportunities?excluded=' + (state.showExcluded ? '1' : '0'));
      if (page === 'prepare') {
        if (!id) { location.hash = 'discover'; return; }
        state.prepareRun = state.applicationRuns.find(r => r.opportunity_id === id) || null;
      }

      if (version !== loadVersion) return;

      const bar = document.getElementById('service-status');
      if (bar && state.config?.capabilities) {
        const c = state.config.capabilities;
        bar.innerHTML = `Lelouvre ${esc(state.config.version)}${state.config.capabilities.read_only ? " · Read-only hosted demo · Fictional data · AI inference disabled" : ""}`;
      }

      const views = {
        today: todayView, discover: () => id ? discoverDetail() : discoverList(), profile: profileView,
        prepare: prepareView, applications: applicationsView, application: applicationDetail,
        interview: interviewView, activity: activityView,
      };
      (views[page] || todayView)();
      if (state.config?.capabilities?.read_only) {
        main.querySelectorAll('button,input,select,textarea').forEach(el => { if (el.dataset.action !== 'reload') el.disabled = true; });
        document.querySelector('.local-note').textContent = 'Read-only hosted preview';
        document.querySelector('footer').textContent = 'Fictional demo data. Changes are disabled. Demo storage is temporary.';
      }
    } catch (error) {
      if (version !== loadVersion) return;
      notify(error.message, true);
      main.innerHTML = `<div class="panel error-panel"><h1>Unable to load</h1><p>${esc(error.message)}</p>${button('Retry', 'reload')}</div>`;
    }
  }

  document.addEventListener('click', async e => {
    const b = e.target.closest('button');
    if (!b || b.disabled) return;
    const actions = ['scout-run', 'scout-toggle', 'source-toggle', 'opportunity-disposition', 'opportunity-prepare', 'excluded-toggle', 'apply-run', 'apply-setting', 'apply-execute', 'packet-approve', 'internship-agent-run', 'internship-agent-enabled', 'internship-agent-apply', 'demo-form-run', 'gemma-ping', 'reload', 'resolve', 'open-log', 'cleardraft'];
    if (actions.includes(b.dataset.action)) {
      b.disabled = true;
      try {
        const action = b.dataset.action;
        if (action === 'scout-run') { await post('/api/agent/run', {}); await load(); notify('Discover check started.'); }
        if (action === 'scout-toggle') { await post('/api/agent/settings', { enabled: !state.agent.enabled }); await load(); }
        if (action === 'source-toggle') { await post('/api/agent/settings', { source_id: b.dataset.id, source_enabled: b.dataset.enable === 'true' }); await load(); }
        if (action === 'opportunity-disposition') {
          const oid = b.dataset.id || state.opportunity?.id;
          await post('/api/opportunities/' + oid + '/disposition', { disposition: b.dataset.value });
          await load();
          notify(b.dataset.value === 'saved' ? 'Saved.' : 'Skipped.');
        }
        if (action === 'packet-approve') { await post('/api/application-runs/' + b.dataset.id + '/approve', {}); await load(); notify('Changes approved.'); }
        if (action === 'opportunity-prepare') { const run = await post('/api/opportunities/' + state.opportunity.id + '/prepare', {}); state.prepareRun = run; await load(); notify(run.status === 'prepared' ? 'Packet ready.' : 'Needs review.'); }
        if (action === 'excluded-toggle') { state.showExcluded = !state.showExcluded; await load(); }
        if (action === 'apply-run') { await post('/api/apply-agent/run', { trigger: 'manual' }); await load(); }
        if (action === 'apply-setting') { const payload = {}; payload[b.dataset.key] = b.dataset.key === 'apply_mode' ? b.dataset.value : b.dataset.value === 'true'; await post('/api/apply-agent/settings', payload); await load(); }
        if (action === 'apply-execute') { await post('/api/application-runs/' + b.dataset.id + '/execute', { auto_submit: true }); await load(); notify('Execute finished.'); }
        if (action === 'demo-form-run') { await post('/api/demo/form-run', {}); await load(); notify('Demo form filled until sponsorship — see Needs you.'); }
        if (action === 'gemma-ping') {
          state.gemmaPing = await post('/api/gemma/chat', { messages: [{ role: 'user', content: 'Reply in one short sentence that Lelouvre uses local Gemma for tailoring.' }] });
          await load();
          notify('Gemma replied.');
        }
        if (action === 'internship-agent-run') { await post('/api/internship-agent/run', {}); await load(); notify('Internship agent started: discover → save → prepare → apply.'); }
        if (action === 'internship-agent-enabled') { await post('/api/internship-agent/settings', { enabled: b.dataset.value === 'true' }); await load(); notify('Agent schedule updated.'); }
        if (action === 'internship-agent-apply') { await post('/api/internship-agent/settings', { auto_apply: b.dataset.value === 'true' }); await load(); notify('Auto-apply setting updated.'); }
        if (action === 'reload') await load();
        if (action === 'resolve') { await post('/api/tasks/' + b.dataset.id + '/resolve', {}); await load(); }
        if (action === 'open-log') { main.querySelector('details')?.setAttribute('open', 'open'); }
        if (action === 'cleardraft') { draft = {}; createKey = crypto.randomUUID(); saveDraft(); await load(); }
      } catch (error) { notify(error.message, true); } finally { b.disabled = false; }
      return;
    }
    if (b.dataset.scope) { state.scope = b.dataset.scope; await load(); return; }
  });

  document.addEventListener('input', e => {
    if (e.target.id === 'search') { state.search = e.target.value; const el = document.getElementById('application-rows'); if (el) el.innerHTML = tableRows(); }
  });
  document.addEventListener('change', e => {
    if (e.target.id === 'stage-filter') { state.stageFilter = e.target.value; const el = document.getElementById('application-rows'); if (el) el.innerHTML = tableRows(); }
  });
  document.addEventListener('submit', async e => {
    const form = e.target;
    if (!['application-form', 'update-form', 'note-form', 'task-form', 'profile-form', 'answers-form'].includes(form.id)) return;
    e.preventDefault();
    if (state.busy) return;
    state.busy = true;
    notify('Saving…');
    try {
      const data = Object.fromEntries(new FormData(form));
      if (form.id === 'profile-form') {
        await post('/api/profile', data);
        state.config = null;
        await load(); notify('Profile saved. Review application packets again before submitting.');
      } else if (form.id === 'answers-form') {
        const answers = {};
        for (const control of form.querySelectorAll('[name]')) {
          if (control.multiple) answers[control.name] = [...control.selectedOptions].map(o => o.value);
          else answers[control.name] = control.value;
        }
        await post('/api/application-runs/' + form.dataset.run + '/answers', { answers });
        await load(); notify('Answers saved. Review and approve the packet.');
      } else if (form.id === 'application-form') {
        await post('/api/applications', data, { 'Idempotency-Key': createKey });
        draft = {}; createKey = crypto.randomUUID(); saveDraft();
        await load(); notify('Saved.');
      } else {
        if (form.id === 'update-form') await post('/api/applications/' + state.detail.id + '/update', { ...data, revision: state.detail.revision });
        if (form.id === 'note-form') await post('/api/applications/' + state.detail.id + '/notes', data);
        if (form.id === 'task-form') await post('/api/tasks', data);
        await load(); notify('Saved.');
      }
    } catch (error) {
      notify(error.message, true);
    } finally { state.busy = false; }
  });

  window.addEventListener('hashchange', load);
  setInterval(() => {
    const [page] = route();
    if (state.busy) return;
    if (page === 'today' && (state.internshipAgent?.runs || []).some(r => r.status === 'running')) load();
    if (page === 'activity' && (state.agent?.runs.some(r => r.status === 'running') || state.applyAgent?.runs.some(r => r.status === 'running'))) load();
  }, 4000);
  load();
})();
