
const $ = (id) => document.getElementById(id);
const state = { plans: [], events: [], lastInvestigation: null, busy: false };

const HOSTS = [
  {key:"frontend", name:"Frontend", role:"Nginx · Web tier", icon:"F"},
  {key:"backend", name:"Backend", role:"FastAPI · Application tier", icon:"B"},
  {key:"database", name:"Database", role:"PostgreSQL · Data tier", icon:"D"}
];

function toast(message, type="info") {
  const el=$('toast');
  el.textContent=message;
  el.className=`toast show ${type}`;
  clearTimeout(toast.timer);
  toast.timer=setTimeout(()=>el.className='toast',3600);
}

function val(metric) {
  if(metric==null) return null;
  if(typeof metric==='number') return metric;
  if(typeof metric==='object' && metric.value!=null) return Number(metric.value);
  return null;
}

function pct(v) {
  return v==null || !Number.isFinite(v) ? '—' : `${v.toFixed(1)}%`;
}

function statusClass(v) {
  const s=String(v||'UNKNOWN').toUpperCase();
  return ['HEALTHY','RUNNING','ACTIVE','CONNECTED','RECOVERED'].includes(s)
    ?'good'
    :['DOWN','FAILED','EXITED','DISCONNECTED','CRITICAL'].includes(s)
    ?'bad':'warn';
}

function setIntegration(prefix, label, ok) {
  $(prefix+'State').textContent=label;
  $(prefix+'Dot').className='dot '+(ok?'good':'bad');
}

function serverCard(host, data) {
  const m=data?.metrics||{};
  const cpu=val(m.cpu_utilization);
  const ram=val(m.memory_utilization);
  const disk=val(m.disk_utilization);
  const status=data?.status||'UNKNOWN';
  const metrics=[['CPU',cpu],['Memory',ram],['Disk',disk]];

  return `<article class="server-card">
    <div class="server-top">
      <div class="host-identity">
        <span class="host-avatar ${host.key}">${host.icon}</span>
        <div><h3>${host.name}</h3><small>${host.role}</small></div>
      </div>
      <span class="status-badge ${statusClass(status)}">${status}</span>
    </div>
    <div class="metric-list">
      ${metrics.map(([label,v])=>`
        <div class="metric-row">
          <div><span>${label}</span><b>${pct(v)}</b></div>
          <div class="meter">
            <i style="width:${Math.max(0,Math.min(100,v||0))}%"></i>
          </div>
        </div>`).join('')}
    </div>
    <div class="server-foot">
      <span>Host: ${data?.technical_name||host.name}</span>
      <span>${data?.item_count??0} Zabbix items</span>
    </div>
  </article>`;
}

async function getJSON(url, options={}) {
  const r=await fetch(url,{
    cache:'no-store',
    ...options,
    headers:{
      'Content-Type':'application/json',
      ...(options.headers||{})
    }
  });

  const body=await r.json().catch(()=>({detail:r.statusText}));

  if(!r.ok) throw new Error(body.detail||body.error||`HTTP ${r.status}`);
  return body;
}

async function loadDashboard() {
  try {
    const [overview, integrations, agent] = await Promise.all([
      getJSON('/api/overview'),
      getJSON('/api/integrations'),
      getJSON('/api/agent/status')
    ]);

    const servers=overview.servers||{};

    $('hostCount').textContent=HOSTS.length;
    $('problemCount').textContent=(overview.problems||[]).length;
    $('agentReady').textContent=agent.status||'READY';
    $('lastUpdated').textContent=new Date().toLocaleTimeString();

    setIntegration('zabbix',integrations.zabbix?.status||'UNKNOWN',integrations.zabbix?.status==='CONNECTED');
    setIntegration('loki',integrations.loki?.status||'UNKNOWN',integrations.loki?.status==='CONNECTED');
    setIntegration('grafana',integrations.grafana?.status||'UNKNOWN',integrations.grafana?.status==='CONFIGURED');

    $('modelState').textContent=agent.model||'Ollama';
    $('agentDot').className='dot good';

    $('serverGrid').innerHTML=HOSTS.map(h=>serverCard(h,servers[h.key])).join('');

    if((overview.problems||[]).some(p=>String(p.name||'').includes('Zabbix agent is not available'))) {
      addEvent(
        'Monitoring node reports a Zabbix agent availability warning. Check whether it belongs to the managed VM set.',
        'warning'
      );
    }
  } catch(e) {
    toast(`Dashboard refresh failed: ${e.message}`,'error');
  }
}

function addEvent(message, level='info') {
  const key=message+'|'+level;
  if(state.events.some(x=>x.key===key)) return;

  state.events.unshift({
    key,
    message,
    level,
    time:new Date().toLocaleTimeString()
  });

  state.events=state.events.slice(0,30);
  renderTimeline();
}

function renderTimeline() {
  $('timelineCount').textContent=`${state.events.length} events`;

  $('timeline').innerHTML=state.events.length
    ?state.events.map(e=>`
      <div class="timeline-item ${e.level}">
        <span class="timeline-dot"></span>
        <div>
          <small>${e.time}</small>
          <p>${escapeHTML(e.message)}</p>
        </div>
      </div>`).join('')
    :'<div class="empty">No agent activity yet.</div>';
}

function escapeHTML(s) {
  return String(s??'').replace(/[&<>"']/g,c=>({
    '&':'&amp;',
    '<':'&lt;',
    '>':'&gt;',
    '"':'&quot;',
    "'":'&#39;'
  }[c]));
}

function setWorkflow(active, done=[]) {
  document.querySelectorAll('.workflow .step').forEach((el,i)=>{
    el.classList.toggle('active',i===active);
    el.classList.toggle('done',done.includes(i));
  });
}

function renderInvestigation(data, source='investigation') {
  state.lastInvestigation=data;
  state.plans=data.plans||[];

  const diag=data.diagnosis||{};
  const findings=diag.findings||[];

  $('diagnosisTitle').textContent=findings.length
    ?`${findings.length} finding${findings.length>1?'s':''} detected`
    :'No confirmed service failure';

  $('diagnosisState').textContent=diag.status||data.agent_status||'ANALYZED';
  $('diagnosisSummary').textContent=diag.summary||data.summary||'Investigation completed.';

  $('findings').className='findings'+(findings.length?'':' empty');

  $('findings').innerHTML=findings.length
    ?findings.map(f=>`
      <div class="finding">
        <div class="finding-head">
          <b>${escapeHTML(f.title)}</b>
          <span class="severity ${String(f.severity||'INFO').toLowerCase()}">${escapeHTML(f.severity||'INFO')}</span>
        </div>
        <p>${escapeHTML(f.summary)}</p>
        <small>
          ${escapeHTML((f.affected_hosts||[]).join(', ')||'Host not specified')}
          · confidence ${Math.round((f.confidence||0)*100)}%
        </small>
        ${(f.evidence||[]).length
          ?`<ul>${f.evidence.map(x=>`<li>${escapeHTML(x)}</li>`).join('')}</ul>`
          :''}
      </div>`).join('')
    :'<div class="empty">No service failure was confirmed by the current SSH checks.</div>';

  renderPlans(state.plans);

  if(source==='fault') {
    setWorkflow(3,[0,1,2]);
    addEvent(
      'Fault injected on Backend. Agent completed observation, diagnosis and remediation planning.',
      'warning'
    );
  } else {
    setWorkflow(2,[0,1]);
    addEvent(
      'AI investigation completed using Zabbix, Loki and SSH evidence.',
      findings.length?'warning':'info'
    );
  }
}

function renderPlans(plans) {
  if(!plans.length) {
    $('planArea').innerHTML=
      '<div class="empty-plan">No remediation required. All observed services are currently healthy.</div>';
    return;
  }

  $('planArea').innerHTML=plans.map(p=>{
    const executable=p.approval_required && p.action_id!=='manual_investigation';

    return `<div class="plan-card">
      <div class="plan-head">
        <div>
          <span class="eyebrow">REMEDIATION PLAN</span>
          <h4>${escapeHTML(p.title)}</h4>
        </div>
        <span class="status-badge ${executable?'warn':'good'}">${escapeHTML(p.status)}</span>
      </div>

      <p>${escapeHTML(p.explanation)}</p>

      <div class="plan-meta">
        <span>Target: <b>${escapeHTML(p.affected_host||'—')}</b></span>
        <span>Risk: <b>${escapeHTML(p.risk||'—')}</b></span>
        <span>Action: <code>${escapeHTML(p.action_id)}</code></span>
      </div>

      ${executable
        ?`<button class="btn btn-primary btn-block approve-btn" data-plan="${escapeHTML(p.plan_id)}">
            ✓ Approve & execute
          </button>
          <small class="approval-hint">
            This runs the fixed allowlisted action only after your approval.
          </small>`
        :''}
    </div>`;
  }).join('');

  document.querySelectorAll('.approve-btn').forEach(btn=>
    btn.addEventListener('click',()=>approvePlan(btn.dataset.plan,btn))
  );
}

async function injectFault() {
  if(state.busy) return;

  const yes=confirm(
    'Inject a controlled fault by stopping the Backend demo container devops-demo-app? The demo API will be temporarily unavailable until remediation.'
  );

  if(!yes) return;

  state.busy=true;
  $('injectBtn').disabled=true;
  $('injectBtn').textContent='Injecting fault…';
  $('faultState').textContent='INJECTING';

  try {
    const data=await getJSON('/api/agent/demo/fault',{
      method:'POST',
      body:JSON.stringify({confirm:true})
    });

    if(!data.fault_injection?.success) {
      throw new Error(data.fault_injection?.error||'Fault injection did not succeed.');
    }

    $('faultState').textContent='INJECTED';
    $('faultState').className='target-status bad';

    addEvent('Backend demo container stopped successfully.','critical');

    renderInvestigation(data.investigation,'fault');

    toast('Fault injected. Agent diagnosis and plan are ready.','success');

    await loadDashboard();

  } catch(e) {
    $('faultState').textContent='FAILED';
    toast(`Fault injection failed: ${e.message}`,'error');
    addEvent(`Fault injection failed: ${e.message}`,'critical');
  } finally {
    state.busy=false;
    $('injectBtn').disabled=false;
    $('injectBtn').textContent='⚡ Inject backend failure';
  }
}

async function investigate() {
  if(state.busy) return;

  state.busy=true;
  $('investigateBtn').disabled=true;
  $('investigateBtn').textContent='Investigating…';

  setWorkflow(0);
  addEvent('Agent started evidence collection.','info');

  try {
    const data=await getJSON('/api/agent/investigate',{method:'POST'});
    renderInvestigation(data);
    toast('Investigation completed.','success');

  } catch(e) {
    toast(`Investigation failed: ${e.message}`,'error');
    addEvent(`Investigation failed: ${e.message}`,'critical');

  } finally {
    state.busy=false;
    $('investigateBtn').disabled=false;
    $('investigateBtn').textContent='✧ Investigate current state';
  }
}

async function approvePlan(planId, button) {
  if(state.busy) return;

  const plan=state.plans.find(p=>p.plan_id===planId);
  if(!plan) return;

  const yes=confirm(
    `Approve remediation?\n\n${plan.title}\nTarget: ${plan.affected_host}\nAction: ${plan.action_id}\n\nThe agent will execute the predefined command and verify recovery.`
  );

  if(!yes) return;

  state.busy=true;
  button.disabled=true;
  button.textContent='Executing & verifying…';

  setWorkflow(4,[0,1,2,3]);

  addEvent(
    `Human approved ${plan.action_id} for ${plan.affected_host}.`,
    'warning'
  );

  try {
    const result=await getJSON(
      `/api/agent/plans/${encodeURIComponent(planId)}/approve`,
      {
        method:'POST',
        body:JSON.stringify({approved:true})
      }
    );

    const recovered=result.status==='RECOVERED';

    setWorkflow(5,[0,1,2,3,4,5]);

    $('resultBanner').hidden=false;
    $('resultBanner').className=`result-banner ${recovered?'success':'warning'}`;

    $('resultBanner').innerHTML=`
      <b>${recovered?'✓ Recovery verified':'! Execution not fully verified'}</b>
      <span>
        ${escapeHTML(result.status)} ·
        ${escapeHTML(result.execution?.description||result.execution?.action_id||'Action attempted')}
      </span>
      <small>${escapeHTML(result.verification?.status||'Verification not run')}</small>
    `;

    addEvent(
      recovered
        ?'Remediation completed and health checks passed.'
        :`Remediation result: ${result.status}. Check execution and verification details.`,
      recovered?'success':'warning'
    );

    const latest=state.plans.find(p=>p.plan_id===planId);
    if(latest) latest.status=result.status;

    renderPlans(state.plans.map(p=>
      p.plan_id===planId
        ?{...p,status:result.status,approval_required:false}
        :p
    ));

    $('faultState').textContent=recovered?'RECOVERED':'CHECK';
    $('faultState').className='target-status '+(recovered?'good':'warn');

    toast(
      recovered
        ?'Backend recovered and verified.'
        :'Action finished; recovery is not confirmed.',
      recovered?'success':'error'
    );

    await loadDashboard();
    await loadLogs();

  } catch(e) {
    toast(`Approval/execution failed: ${e.message}`,'error');
    addEvent(`Execution failed: ${e.message}`,'critical');

    button.disabled=false;
    button.textContent='Retry approval';

  } finally {
    state.busy=false;
  }
}

async function loadLogs() {
  try {
    const data=await getJSON('/api/logs?minutes=15&limit=18');
    const rows=data.logs||[];

    $('logList').innerHTML=rows.length
      ?rows.slice(-12).reverse().map(row=>`
        <div class="log-row">
          <span class="log-mark ${/error|fail|critical/i.test(row.line||'')?'bad':'good'}"></span>
          <div>
            <p>${escapeHTML(row.line||'')}</p>
            <small>
              ${escapeHTML(row.host||row.job||'log')}
              · ${escapeHTML(row.timestamp||'')}
            </small>
          </div>
        </div>`).join('')
      :'<div class="empty">No recent log entries.</div>';

  } catch(e) {
    $('logList').innerHTML=
      `<div class="empty">Loki logs unavailable: ${escapeHTML(e.message)}</div>`;
  }
}

$('refreshBtn').addEventListener('click',()=>{
  loadDashboard();
  loadLogs();
});

$('injectBtn').addEventListener('click',injectFault);
$('investigateBtn').addEventListener('click',investigate);

loadDashboard();
loadLogs();

setInterval(loadDashboard,10000);
setInterval(loadLogs,20000);
