async function getStatus(){
  try{
    const r=await fetch("/api/status",{cache:"no-store"});
    updateDashboard(await r.json());
  }catch(e){console.error(e)}
}
function setStatus(id,v){
  const e=document.getElementById(id);
  e.textContent="● "+v;
  e.className="big "+(v==="HEALTHY"?"healthy":v==="DOWN"?"down":"unknown");
}
function pill(id,v){
  const e=document.getElementById(id);
  e.textContent=v;
  e.className="pill "+(v==="HEALTHY"?"healthy":v==="DOWN"?"down":"");
}
function metric(prefix,m){
  const cpu=m.cpu,ram=m.ram_percent,disk=m.disk_percent;
  document.getElementById(prefix+"Cpu").textContent=cpu==null?"--":cpu.toFixed(1)+"%";
  document.getElementById(prefix+"Ram").textContent=ram==null?"--":ram.toFixed(1)+"%";
  document.getElementById(prefix+"Disk").textContent=disk==null?"--":disk.toFixed(1)+"%";
  document.getElementById(prefix+"CpuBar").style.width=Math.min(cpu||0,100)+"%";
  document.getElementById(prefix+"RamBar").style.width=Math.min(ram||0,100)+"%";
  document.getElementById(prefix+"DiskBar").style.width=Math.min(disk||0,100)+"%";
  document.getElementById(prefix+"Details").textContent="Uptime: "+(m.uptime||"--");
}
function updateDashboard(d){
  setStatus("frontendStatus",d.frontend);
  setStatus("backendStatus",d.backend);
  setStatus("databaseStatus",d.database);
  document.getElementById("agentStatus").textContent=d.agent;
  document.getElementById("lastCheck").textContent="Last check: "+(d.last_check||"--");

  const s=d.servers||{};
  if(s.frontend){pill("frontendVm",s.frontend.status);metric("frontend",s.frontend)}
  if(s.backend){pill("backendVm",s.backend.status);metric("backend",s.backend)}
  if(s.database){pill("databaseVm",s.database.status);metric("database",s.database)}

  const inc=document.getElementById("incident");
  const incidentText = d.incident ? (typeof d.incident === "string" ? d.incident : d.incident.summary || d.incident.type || "Active incident") : "";
  inc.textContent=incidentText ? "⚠ "+incidentText : "No active incident";
  inc.style.color=incidentText?"#ff5263":"#43df89";

  document.getElementById("action").textContent=d.action?"AI Action: "+d.action:"No AI action yet";
  document.getElementById("verification").textContent=d.verification?"Verification: "+d.verification:"";

  const t=document.getElementById("timeline");
  t.innerHTML="";
  for(const ev of d.events||[]){
    const div=document.createElement("div");
    div.className="event "+ev.level;
    const time=document.createElement("span");
    time.className="time";time.textContent=ev.time;
    div.append(time,document.createTextNode(ev.message));
    t.appendChild(div);
  }
}
async function injectFault(){
  const box=document.getElementById("actionResult");
  box.textContent="Injecting backend failure...";
  try{
    const r=await fetch("/api/fault",{method:"POST"});
    const d=await r.json();
    box.textContent=d.status==="success"?"Fault injected successfully.":"Fault injection failed: "+(d.error||"unknown");
    await getStatus();
  }catch(e){box.textContent="Fault injection failed: "+e}
}
async function runRemediation(){
  const box=document.getElementById("actionResult");
  box.textContent="Starting AI remediation...";
  try{
    const r=await fetch("/api/analyze",{method:"POST"});
    const d=await r.json();
    box.textContent=d.message||d.status;
    await getStatus();
  }catch(e){box.textContent="AI remediation failed: "+e}
}
getStatus();
setInterval(getStatus,2000);


// Layered pipeline status (added by modular refactor).
function renderPipeline(d){
  const source = d.sources || {};
  const layers = d.layers || {};
  const root = document.getElementById("timeline");
  if(!root) return;
  const summary = document.getElementById("pipelineSummary");
  if(summary){
    summary.textContent = "Sources: Zabbix "+(source.zabbix||"UNKNOWN")+
      " · Loki "+(source.loki||"UNKNOWN")+" · Ollama "+(source.ollama||"UNKNOWN")+
      " | Deterministic "+(layers.deterministic||"WAITING")+
      " | Laya "+(layers.laya||"WAITING")+
      " | Ministral "+(layers.ministral||"WAITING")+
      " | Policy "+(layers.policy||"WAITING")+
      " | Remediation "+(layers.remediation||"IDLE");
  }
}
const _originalUpdateDashboard = updateDashboard;
updateDashboard = function(d){
  _originalUpdateDashboard(d);
  renderPipeline(d);
};
