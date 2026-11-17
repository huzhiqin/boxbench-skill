"use strict";
const $ = id => document.getElementById(id);
const statusNames = {pending:"等待中", running:"运行中", done:"已执行", failed:"异常", skipped:"已跳过"};
const tiles = ["#4469ee", "#242b29", "#f17b44", "#4469ee", "#d88739", "#506bdf", "#262e29", "#e17c40", "#5277db", "#768953", "#e18b47", "#30382c"];
// Serpentine graph: real stage state drives every node and active edge.
const positions = [[1,1],[2,1],[3,1],[4,1],[4,2],[3,2],[2,2],[1,2],[1,3],[2,3],[3,3],[4,3]];
let state = null, selected = null, follow = true, sequence = -1, nodeButtons = [], lastLogs = "", disconnected = false, planKey = "";
const shortTime = t => new Date(t * 1000).toLocaleTimeString("zh-CN", {hour12:false});
function duration(seconds) { const s = Math.max(0, Math.floor(seconds)); return `${Math.floor(s/60).toString().padStart(2,"0")}:${(s%60).toString().padStart(2,"0")}`; }
function makeIcon(name) {const img=document.createElement("img");img.src=`icons/${name}.svg`;img.alt="";return img;}
function initNodes() {
  nodeButtons = state.stages.map((s,i) => {
    const node=document.createElement("button"); node.className="node";node.dataset.stage=s.id;
    const [x,y]=positions[i];node.style.gridColumn=x;node.style.gridRow=y;node.style.setProperty("--tile",tiles[i]);
    if(i===1||i===6||i===11)node.classList.add("tone-dark");
    const tile=document.createElement("span");tile.className="node-tile";tile.append(makeIcon(s.icon));
    const badge=document.createElement("span");badge.className="node-state";badge.append(makeIcon("check"));
    const title=document.createElement("strong");title.textContent=s.name;
    const code=document.createElement("span");code.className="node-code";code.textContent=s.code;
    node.append(tile,badge,title,code);node.addEventListener("click",()=>{selected=s.id;follow=false;renderNodes();renderDetail();});
    $("nodes").append(node);return node;
  });
}
function renderNodes(){
  state.stages.forEach((s,i)=>{
    const node=nodeButtons[i];Object.keys(statusNames).forEach(c=>node.classList.toggle(c,c===s.status));
    node.classList.toggle("selected",selected===s.id);node.setAttribute("aria-label",`${s.name}，${statusNames[s.status]}`);
    node.setAttribute("aria-pressed",String(selected===s.id));
    node.querySelector(".node-state img").src=`icons/${s.status==="running"?"loader-2":s.status==="failed"?"exclamation-mark":s.status==="skipped"?"minus":"check"}.svg`;
  });
}
function renderDetail(){
  if(!state)return;
  const s=state.stages.find(s=>s.id===selected)||state.stages[0];const i=state.stages.indexOf(s);
  $("detail-index").textContent=`${String(i+1).padStart(2,"0")} / 12`;
  $("detail-icon").replaceChildren(makeIcon(s.icon));$("detail-name").textContent=s.name;
  $("detail-status").textContent=statusNames[s.status];$("detail-status").className=`detail-status ${s.status}`;
  $("detail-description").textContent=s.description;$("detail-code").textContent=s.code;
  $("detail-start").textContent=s.started?shortTime(s.started):"—";
  $("detail-duration").textContent=s.started?duration((s.ended||Date.now()/1000)-s.started):"—";
  $("detail-message").textContent=s.detail||(s.status==="pending"?"等待测试进程上报状态。":"步骤已执行，指标结论请查看最终报告。");
  $("follow").disabled=follow;$("follow").lastChild.textContent=follow?"已跟随当前步骤":"跟随当前步骤";
}
function renderLogs(){
  const signature=JSON.stringify(state.logs);if(signature===lastLogs)return;lastLogs=signature;
  $("log-count").textContent=state.logs.length;$("log-body").replaceChildren();
  for(const line of state.logs){const row=document.createElement("div");row.className="log-line";
    const time=document.createElement("span");time.className="log-time";time.textContent=shortTime(line.time);
    const text=document.createElement("span");text.className="log-text";text.textContent=line.text;row.append(time,text);$("log-body").append(row);}
  if(!state.logs.length){const p=document.createElement("p");p.className="empty-log";p.textContent="等待测试进程输出…";$("log-body").append(p);}
  if($("autoscroll").checked)$("log-body").scrollTop=$("log-body").scrollHeight;
}
function update(){
  $("run-title").textContent=state.title;$("demo-tag").hidden=!state.demo;
  $("model-name").textContent=state.model;$("model-name").title=state.model;
  const issues=[...state.stages,...state.models.flatMap(m=>m.stages)].some(s=>s.status==="failed");
  $("run-status").textContent=state.status==="running"?"测试运行中":state.status==="failed"?"进程异常退出":issues?"已结束 · 含异常":"测试已结束";
  $("run-status").classList.toggle("failed",state.status==="failed"||issues);
  const completed=state.stages.filter(s=>["done","failed","skipped"].includes(s.status)).length;
  $("completed").textContent=completed;$("progress").value=completed;
  if(follow)selected=state.current||[...state.stages].reverse().find(s=>s.status==="failed")?.id||[...state.stages].reverse().find(s=>s.status!=="pending")?.id||state.stages[0].id;
  const nextPlan=state.stages.map(s=>s.id).join(",");
  if(planKey!==nextPlan){$("nodes").replaceChildren();initNodes();planKey=nextPlan;measure();}
  renderNodes();renderDetail();renderLogs();tick();
}
function tick(){if(!state)return;$("elapsed").textContent=duration((state.ended||Date.now()/1000)-state.started);renderDetail();}
$("follow").addEventListener("click",()=>{follow=true;update();});
$("export").addEventListener("click",()=>{if(!state)return;const blob=new Blob([JSON.stringify(state,null,2)],{type:"application/json"});const url=URL.createObjectURL(blob);const a=document.createElement("a");a.href=url;a.download=state.demo?"boxbench_DEMO_snapshot.json":"boxbench_run_snapshot.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);});
$("copy-logs").addEventListener("click",async()=>{if(!state)return;try{await navigator.clipboard.writeText(state.logs.map(l=>`[${shortTime(l.time)}] ${l.text}`).join("\n"));$("copy-logs").textContent="已复制";}catch{$("copy-logs").textContent="复制受限，请导出快照";}setTimeout(()=>$("copy-logs").textContent="复制日志",2200);});
async function poll(){
  try{const r=await fetch("api/state",{cache:"no-store",signal:AbortSignal.timeout(5000)});if(!r.ok)throw Error(r.status);const next=await r.json();
    $("connection-warning").hidden=true;$("sync-label").classList.remove("offline");$("sync-label").textContent="实时同步";disconnected=false;
    state=next;if(sequence!==state.sequence){sequence=state.sequence;update();}
  }catch{disconnected=true;$("connection-warning").hidden=false;$("sync-label").textContent="等待重连";$("sync-label").classList.add("offline");}
  setTimeout(poll,800);
}
// Canvas is a data visualization, not an illustration. Connections and particles
// reflect the current node state; the background dots provide graph coordinates.
const canvas=$("connections"),ctx=canvas.getContext("2d"),reduced=matchMedia("(prefers-reduced-motion: reduce)");
let w=0,h=0,dpr=1,points=[];
function measure(){const rect=$("flow-canvas").getBoundingClientRect();w=rect.width;h=rect.height;dpr=devicePixelRatio||1;canvas.width=w*dpr;canvas.height=h*dpr;ctx.setTransform(dpr,0,0,dpr,0,0);points=nodeButtons.map(n=>{const r=n.querySelector(".node-tile").getBoundingClientRect();return{x:r.x+r.width/2-rect.x,y:r.y+r.height/2-rect.y,size:r.width};});}
new ResizeObserver(measure).observe($("flow-canvas"));
function draw(time){
  ctx.clearRect(0,0,w,h);ctx.fillStyle="#dce1d3";for(let x=13;x<w;x+=18)for(let y=11;y<h;y+=18){ctx.beginPath();ctx.arc(x,y,.7,0,Math.PI*2);ctx.fill();}
  if(state&&points.length===12){for(let i=1;i<points.length;i++){
    const a=points[i-1],b=points[i],s=state.stages[i],prev=state.stages[i-1];const horizontal=Math.abs(a.y-b.y)<15;
    const side=a.x>w/2?1:-1;
    const from={x:a.x+(horizontal?Math.sign(b.x-a.x):side)*(a.size/2+3),y:a.y};
    const to={x:b.x+(horizontal?-Math.sign(b.x-a.x):side)*(b.size/2+3),y:b.y};
    const lane=side>0?w-19:19;
    const active=s.status==="running"&&prev.status==="done"&&!disconnected&&state.status==="running";
    const done=prev.status==="done"&&s.status==="done";ctx.beginPath();ctx.moveTo(from.x,from.y);
    if(horizontal)ctx.lineTo(to.x,to.y);else ctx.bezierCurveTo(lane,from.y,lane,to.y,to.x,to.y);
    ctx.strokeStyle=done||active?"#8fa97a":"#d7ddcd";ctx.lineWidth=done||active?2:1.5;ctx.setLineDash(done?[]:[4,5]);ctx.stroke();ctx.setLineDash([]);
    if(active&&!reduced.matches){for(let p=0;p<3;p++){const t=(time/2100+p/3)%1,u=1-t;
      const x=horizontal?from.x+(to.x-from.x)*t:u*u*u*from.x+3*u*u*t*lane+3*u*t*t*lane+t*t*t*to.x;
      const y=horizontal?from.y:u*u*u*from.y+3*u*u*t*from.y+3*u*t*t*to.y+t*t*t*to.y;
      ctx.beginPath();ctx.arc(x,y,3,0,Math.PI*2);ctx.fillStyle="#adc94f";ctx.fill();}}
  }}
  requestAnimationFrame(draw);
}
poll();setInterval(()=>{tick();measure();},1000);requestAnimationFrame(draw);
