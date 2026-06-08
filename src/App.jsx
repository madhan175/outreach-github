import { useState, useEffect, useRef, useCallback } from "react";

// ── API base ──────────────────────────────────────────────────────────────────
const API = "http://localhost:8000/api";

// ── API client ────────────────────────────────────────────────────────────────
const api = {
  health:  ()               => fetch(`${API}/health`).then(r => r.json()),
  start:   (body)           => fetch(`${API}/run`, { method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body) }).then(r => r.json()),
  getRun:  (id)             => fetch(`${API}/run/${id}`).then(r => r.json()),
  runs:    ()               => fetch(`${API}/runs`).then(r => r.json()),
  confirm: (id)             => fetch(`${API}/send/${id}`,   { method:"POST" }).then(r => r.json()),
  cancel:  (id)             => fetch(`${API}/cancel/${id}`, { method:"POST" }).then(r => r.json()),
};

// ── Colours / constants ───────────────────────────────────────────────────────
const STATUS_META = {
  pending:    { label:"Pending",    color:"#6b7280", bg:"#6b728015" },
  stage1:     { label:"Apollo",     color:"#60a5fa", bg:"#60a5fa15" },
  stage2:     { label:"Prospeo",    color:"#a78bfa", bg:"#a78bfa15" },
  checkpoint: { label:"Checkpoint", color:"#fbbf24", bg:"#fbbf2415" },
  stage3:     { label:"Brevo",      color:"#34d399", bg:"#34d39915" },
  done:       { label:"Done",       color:"#34d399", bg:"#34d39920" },
  failed:     { label:"Failed",     color:"#f87171", bg:"#f8717115" },
  cancelled:  { label:"Cancelled",  color:"#9ca3af", bg:"#9ca3af15" },
};

const LOG_COLORS = {
  info:"#9b9cb8", success:"#34d399", warning:"#fbbf24", error:"#f87171", debug:"#5c5e78",
};

// ── Tiny components ───────────────────────────────────────────────────────────
function Badge({ status }) {
  const m = STATUS_META[status] || STATUS_META.pending;
  return (
    <span style={{
      display:"inline-flex", alignItems:"center", gap:5,
      padding:"3px 10px", borderRadius:20, fontSize:11, fontWeight:600,
      background:m.bg, color:m.color, border:`1px solid ${m.color}30`,
      fontFamily:"'DM Mono', monospace",
    }}>
      {status === "stage1" || status === "stage2" || status === "stage3"
        ? <span style={{width:6,height:6,borderRadius:"50%",background:m.color,
            animation:"pulse 1.2s infinite",display:"inline-block"}}/>
        : null}
      {m.label}
    </span>
  );
}

function Spinner({ size=16, color="#6c63ff" }) {
  return (
    <span style={{
      display:"inline-block", width:size, height:size,
      border:`2px solid ${color}30`, borderTopColor:color,
      borderRadius:"50%", animation:"spin .7s linear infinite", flexShrink:0,
    }}/>
  );
}

function Avatar({ name, color="#6c63ff" }) {
  const initials = (name||"?").split(" ").map(w=>w[0]).join("").slice(0,2).toUpperCase();
  return (
    <span style={{
      width:32, height:32, borderRadius:"50%", background:color,
      display:"inline-flex", alignItems:"center", justifyContent:"center",
      fontSize:12, fontWeight:700, color:"#fff", flexShrink:0,
      fontFamily:"'Syne', sans-serif",
    }}>{initials}</span>
  );
}

const AVATAR_COLORS = ["#6c63ff","#38bdf8","#34d399","#f472b6","#fbbf24","#a78bfa","#fb923c"];

// ── Main App ──────────────────────────────────────────────────────────────────
export default function App() {
  const [view, setView]         = useState("dashboard"); // dashboard | run | history
  const [health, setHealth]     = useState(null);
  const [activeRun, setActiveRun] = useState(null);
  const [history, setHistory]   = useState([]);

  // Poll health on mount
  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth({ status:"error" }));
    api.runs().then(setHistory).catch(()=>{});
  }, []);

  const onRunStarted = (run) => {
    setActiveRun(run);
    setView("run");
  };

  const refreshHistory = () => api.runs().then(setHistory).catch(()=>{});

  return (
    <>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Syne:wght@400;600;700;800&family=DM+Sans:wght@300;400;500&family=DM+Mono:wght@400;500&display=swap');
        *,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
        html,body,#root{height:100%;background:#08090d;color:#f0f0f8;font-family:'DM Sans',sans-serif;font-size:14px}
        ::-webkit-scrollbar{width:4px;height:4px}
        ::-webkit-scrollbar-track{background:transparent}
        ::-webkit-scrollbar-thumb{background:#ffffff20;border-radius:4px}
        @keyframes spin{to{transform:rotate(360deg)}}
        @keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
        @keyframes fadeUp{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
        @keyframes slideIn{from{opacity:0;transform:translateX(-8px)}to{opacity:1;transform:translateX(0)}}
        input,button{font-family:inherit}
        button{cursor:pointer}
      `}</style>

      <div style={{display:"flex",flexDirection:"column",height:"100vh"}}>
        <Nav view={view} setView={setView} health={health} />
        <div style={{flex:1,overflow:"auto"}}>
          {view === "dashboard" && (
            <Dashboard
              health={health}
              history={history}
              onStart={onRunStarted}
              onViewRun={(run) => { setActiveRun(run); setView("run"); }}
            />
          )}
          {view === "run" && (
            <RunView
              initialRun={activeRun}
              onDone={refreshHistory}
            />
          )}
          {view === "history" && (
            <History
              runs={history}
              onRefresh={refreshHistory}
              onView={(run) => { setActiveRun(run); setView("run"); }}
            />
          )}
        </div>
      </div>
    </>
  );
}

// ── Nav ───────────────────────────────────────────────────────────────────────
function Nav({ view, setView, health }) {
  const keys = health?.keys;
  const allOk = keys && keys.apollo && keys.prospeo && keys.brevo;
  return (
    <header style={{
      display:"flex", alignItems:"center", gap:8,
      padding:"0 28px", height:54,
      background:"#0f1117", borderBottom:"1px solid #ffffff0f",
      flexShrink:0, position:"sticky", top:0, zIndex:100,
    }}>
      <div style={{
        fontFamily:"'Syne',sans-serif", fontSize:17, fontWeight:800,
        background:"linear-gradient(135deg,#fff,#a78bfa)",
        WebkitBackgroundClip:"text", WebkitTextFillColor:"transparent",
        marginRight:24, letterSpacing:"-.5px",
      }}>ReachFlow</div>

      {["dashboard","run","history"].map(v => (
        <button key={v} onClick={() => setView(v)} style={{
          padding:"6px 14px", borderRadius:8, border:"none",
          background: view===v ? "#1c1f2e" : "transparent",
          color: view===v ? "#f0f0f8" : "#9b9cb8",
          fontSize:13, fontWeight: view===v ? 500 : 400,
          transition:".15s", textTransform:"capitalize",
        }}>{v === "run" ? "Live run" : v}</button>
      ))}

      <div style={{flex:1}}/>

      {/* API key status indicators */}
      {keys && (
        <div style={{display:"flex",gap:6,alignItems:"center"}}>
          {[["A","apollo"],["P","prospeo"],["B","brevo"]].map(([l,k]) => (
            <div key={k} title={`${k}: ${keys[k] ? "connected":"missing"}`} style={{
              width:24, height:24, borderRadius:6, fontSize:10, fontWeight:700,
              display:"flex", alignItems:"center", justifyContent:"center",
              background: keys[k] ? "#34d39920" : "#f8717120",
              color: keys[k] ? "#34d399" : "#f87171",
              border:`1px solid ${keys[k] ? "#34d39940":"#f8717140"}`,
              fontFamily:"'DM Mono',monospace",
            }}>{l}</div>
          ))}
        </div>
      )}
      {health && (
        <div style={{
          display:"flex", alignItems:"center", gap:5, fontSize:11,
          color: allOk ? "#34d399" : "#fbbf24",
          padding:"4px 10px", borderRadius:6,
          background: allOk ? "#34d39910" : "#fbbf2410",
          border:`1px solid ${allOk ? "#34d39930":"#fbbf2430"}`,
          fontFamily:"'DM Mono',monospace",
        }}>
          <span style={{width:6,height:6,borderRadius:"50%",
            background: allOk ? "#34d399":"#fbbf24"}}/>
          {allOk ? "all systems ok" : "check api keys"}
        </div>
      )}
    </header>
  );
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
function Dashboard({ health, history, onStart, onViewRun }) {
  const [domain, setDomain] = useState("");
  const [limit, setLimit]   = useState("");
  const [dryRun, setDryRun] = useState(false);
  const [loading, setLoading] = useState(false);
  const [err, setErr]         = useState("");

  const submit = async () => {
    if (!domain.trim()) { setErr("Enter a domain first"); return; }
    setErr(""); setLoading(true);
    try {
      const run = await api.start({
        domain: domain.trim(),
        limit: limit ? parseInt(limit) : null,
        dry_run: dryRun,
      });
      if (run.run_id) onStart(run);
      else setErr(run.detail || "Failed to start run");
    } catch(e) {
      setErr("Cannot reach backend. Is uvicorn running on :8000?");
    } finally {
      setLoading(false);
    }
  };

  const recent = history.slice(0, 5);
  const totalSent = history.reduce((a,r) => a + (r.sent||0), 0);
  const doneRuns  = history.filter(r => r.status === "done").length;

  return (
    <div style={{padding:"32px 40px", maxWidth:1100, margin:"0 auto", animation:"fadeUp .3s ease"}}>
      <div style={{marginBottom:32}}>
        <h1 style={{fontFamily:"'Syne',sans-serif", fontSize:26, fontWeight:700, marginBottom:6}}>
          Outreach pipeline
        </h1>
        <p style={{color:"#9b9cb8", fontSize:13}}>
          Apollo.io → Prospeo → Brevo · one domain in, verified emails out
        </p>
      </div>

      {/* Stats */}
      <div style={{display:"grid", gridTemplateColumns:"repeat(3,1fr)", gap:14, marginBottom:32}}>
        {[
          { label:"Total runs",    value:history.length,       color:"#6c63ff" },
          { label:"Emails sent",   value:totalSent,            color:"#34d399" },
          { label:"Completed",     value:doneRuns,             color:"#38bdf8" },
        ].map(s => (
          <div key={s.label} style={{
            background:"#1c1f2e", border:"1px solid #ffffff0f",
            borderRadius:12, padding:"18px 20px",
            borderTop:`2px solid ${s.color}`,
          }}>
            <div style={{fontSize:11,color:"#5c5e78",textTransform:"uppercase",letterSpacing:".5px",marginBottom:8}}>{s.label}</div>
            <div style={{fontFamily:"'Syne',sans-serif",fontSize:30,fontWeight:700}}>{s.value}</div>
          </div>
        ))}
      </div>

      {/* Run form */}
      <div style={{
        background:"#1c1f2e", border:"1px solid #ffffff0f",
        borderRadius:16, padding:28, marginBottom:28,
      }}>
        <div style={{fontFamily:"'Syne',sans-serif",fontSize:15,fontWeight:600,marginBottom:20}}>
          New pipeline run
        </div>

        <div style={{display:"flex",gap:12,alignItems:"flex-end",flexWrap:"wrap"}}>
          <div style={{flex:"1 1 280px"}}>
            <label style={{display:"block",fontSize:11,color:"#9b9cb8",marginBottom:6,letterSpacing:".3px"}}>
              SEED DOMAIN
            </label>
            <input
              value={domain}
              onChange={e=>setDomain(e.target.value)}
              onKeyDown={e=>e.key==="Enter"&&submit()}
              placeholder="e.g. stripe.com"
              style={{
                width:"100%", padding:"10px 14px",
                background:"#242738", border:"1px solid #ffffff15",
                borderRadius:10, color:"#f0f0f8",
                fontFamily:"'DM Mono',monospace", fontSize:14,
                outline:"none", transition:".15s",
              }}
              onFocus={e=>{e.target.style.borderColor="#6c63ff"}}
              onBlur={e=>{e.target.style.borderColor="#ffffff15"}}
            />
          </div>
          <div style={{flex:"0 0 120px"}}>
            <label style={{display:"block",fontSize:11,color:"#9b9cb8",marginBottom:6,letterSpacing:".3px"}}>
              LIMIT (OPT)
            </label>
            <input
              value={limit}
              onChange={e=>setLimit(e.target.value.replace(/\D/,""))}
              placeholder="e.g. 5"
              style={{
                width:"100%", padding:"10px 14px",
                background:"#242738", border:"1px solid #ffffff15",
                borderRadius:10, color:"#f0f0f8", fontSize:14,
                outline:"none", transition:".15s",
              }}
              onFocus={e=>{e.target.style.borderColor="#6c63ff"}}
              onBlur={e=>{e.target.style.borderColor="#ffffff15"}}
            />
          </div>
          <label style={{
            display:"flex", alignItems:"center", gap:8, cursor:"pointer",
            padding:"10px 14px", background:"#242738",
            border:`1px solid ${dryRun?"#fbbf2440":"#ffffff15"}`,
            borderRadius:10, color: dryRun ? "#fbbf24":"#9b9cb8",
            fontSize:13, transition:".15s", userSelect:"none",
            flex:"0 0 auto",
          }}>
            <input type="checkbox" checked={dryRun} onChange={e=>setDryRun(e.target.checked)}
              style={{accentColor:"#fbbf24"}}/>
            Dry run
          </label>
          <button onClick={submit} disabled={loading} style={{
            padding:"10px 28px", flexShrink:0,
            background: loading ? "#6c63ff60" : "linear-gradient(135deg,#6c63ff,#a78bfa)",
            border:"none", borderRadius:10,
            color:"#fff", fontFamily:"'Syne',sans-serif",
            fontSize:14, fontWeight:600, transition:".15s",
            display:"flex", alignItems:"center", gap:8,
          }}>
            {loading ? <><Spinner size={14} color="#fff"/>Starting…</> : "⚡ Run pipeline"}
          </button>
        </div>

        {err && (
          <div style={{
            marginTop:14, padding:"10px 14px",
            background:"#f8717115", border:"1px solid #f8717130",
            borderRadius:8, color:"#f87171", fontSize:12,
          }}>{err}</div>
        )}

        {dryRun && (
          <div style={{
            marginTop:12, fontSize:12, color:"#fbbf24",
            padding:"8px 12px", background:"#fbbf2410",
            borderRadius:8, border:"1px solid #fbbf2420",
          }}>
            ⚠ Dry run mode — Brevo will NOT send emails. Use this to test the pipeline safely.
          </div>
        )}
      </div>

      {/* Recent runs */}
      {recent.length > 0 && (
        <div style={{background:"#1c1f2e",border:"1px solid #ffffff0f",borderRadius:16,overflow:"hidden"}}>
          <div style={{
            padding:"14px 20px", borderBottom:"1px solid #ffffff0f",
            display:"flex", justifyContent:"space-between", alignItems:"center",
          }}>
            <span style={{fontFamily:"'Syne',sans-serif",fontSize:13,fontWeight:600}}>Recent runs</span>
            <button onClick={()=>null} style={{
              fontSize:11,color:"#a78bfa",background:"none",border:"none",padding:0,
            }}>view all →</button>
          </div>
          {recent.map(r => (
            <div key={r.run_id} onClick={() => onViewRun(r)} style={{
              display:"flex", alignItems:"center", gap:14,
              padding:"12px 20px", borderBottom:"1px solid #ffffff08",
              cursor:"pointer", transition:".15s",
            }}
            onMouseEnter={e=>e.currentTarget.style.background="#ffffff04"}
            onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
              <div style={{fontFamily:"'DM Mono',monospace",fontSize:12,color:"#6c63ff",width:64,flexShrink:0}}>
                #{r.run_id}
              </div>
              <div style={{flex:1}}>
                <div style={{fontSize:13,fontWeight:500}}>{r.domain}</div>
                <div style={{fontSize:11,color:"#5c5e78",marginTop:2}}>
                  {r.lookalikes} lookalikes · {r.contacts} contacts · {r.sent} sent
                </div>
              </div>
              <Badge status={r.status}/>
              <div style={{fontSize:11,color:"#5c5e78",fontFamily:"'DM Mono',monospace",flexShrink:0}}>
                {new Date(r.created_at).toLocaleTimeString()}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ── Run View ──────────────────────────────────────────────────────────────────
function RunView({ initialRun, onDone }) {
  const [run, setRun]           = useState(initialRun);
  const [logs, setLogs]         = useState([]);
  const [contacts, setContacts] = useState([]);
  const [lookalikes, setLookalikes] = useState([]);
  const [sendResults, setSendResults] = useState([]);
  const [confirming, setConfirming]   = useState(false);
  const logsRef = useRef(null);
  const esRef   = useRef(null);

  const runId = run?.run_id;

  // Poll run state + connect SSE
  useEffect(() => {
    if (!runId) return;

    // SSE connection
    const es = new EventSource(`${API}/stream/${runId}`);
    esRef.current = es;

    es.onmessage = (e) => {
      try {
        const ev = JSON.parse(e.data);
        if (ev.type === "ping") return;
        if (ev.type === "close") { es.close(); return; }
        if (ev.type === "log") {
          setLogs(prev => [...prev, ev]);
        }
        if (ev.type === "stage1_done") setLookalikes(ev.lookalikes || []);
        if (ev.type === "stage2_done") setContacts(ev.contacts || []);
        if (ev.type === "done") {
          setSendResults(ev.send_results || []);
          onDone?.();
        }
        // Refresh run state
        api.getRun(runId).then(r => {
          setRun(r);
          setLookalikes(r.lookalikes || []);
          setContacts(r.contacts || []);
          setSendResults(r.send_results || []);
        });
      } catch(_) {}
    };

    es.onerror = () => es.close();

    // Initial fetch
    api.getRun(runId).then(r => {
      setRun(r);
      setLogs(r.logs || []);
      setLookalikes(r.lookalikes || []);
      setContacts(r.contacts || []);
      setSendResults(r.send_results || []);
    });

    return () => es.close();
  }, [runId]);

  // Auto-scroll logs
  useEffect(() => {
    if (logsRef.current) logsRef.current.scrollTop = logsRef.current.scrollHeight;
  }, [logs]);

  const handleConfirm = async () => {
    setConfirming(true);
    await api.confirm(runId);
    setConfirming(false);
  };

  const handleCancel = async () => {
    await api.cancel(runId);
    api.getRun(runId).then(setRun);
  };

  if (!run) return (
    <div style={{display:"flex",alignItems:"center",justifyContent:"center",height:"60vh"}}>
      <div style={{textAlign:"center",color:"#9b9cb8"}}>
        <div style={{fontSize:32,marginBottom:12}}>⚡</div>
        <div>No active run. Start one from the dashboard.</div>
      </div>
    </div>
  );

  const status = run.status;
  const isLive = ["stage1","stage2","stage3"].includes(status);
  const isCheckpoint = status === "checkpoint";
  const isDone = status === "done";
  const isFailed = status === "failed";

  // Stage progress
  const stages = [
    { key:"stage1", label:"Apollo.io", sub:"Find lookalike companies", color:"#60a5fa",
      done: !["pending","stage1"].includes(status) || isDone,
      active: status === "stage1" },
    { key:"stage2", label:"Prospeo", sub:"Decision-makers + emails", color:"#a78bfa",
      done: !["pending","stage1","stage2"].includes(status) || isDone,
      active: status === "stage2" },
    { key:"stage3", label:"Brevo", sub:"Send outreach emails", color:"#34d399",
      done: isDone,
      active: status === "stage3" },
  ];

  const sentCount   = sendResults.filter(r=>r.status==="sent").length;
  const failedCount = sendResults.filter(r=>r.status==="failed").length;
  const dryCount    = sendResults.filter(r=>r.status==="dry_run").length;

  return (
    <div style={{padding:"28px 40px", maxWidth:1200, margin:"0 auto", animation:"fadeUp .3s ease"}}>
      {/* Header */}
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:28}}>
        <div>
          <div style={{display:"flex",alignItems:"center",gap:12,marginBottom:4}}>
            <h1 style={{fontFamily:"'Syne',sans-serif",fontSize:22,fontWeight:700}}>
              {run.domain}
            </h1>
            <Badge status={status}/>
            {run.dry_run && (
              <span style={{
                fontSize:10,padding:"3px 8px",borderRadius:6,
                background:"#fbbf2415",color:"#fbbf24",
                border:"1px solid #fbbf2430",fontFamily:"'DM Mono',monospace",
              }}>DRY RUN</span>
            )}
          </div>
          <div style={{fontSize:12,color:"#5c5e78",fontFamily:"'DM Mono',monospace"}}>
            #{run.run_id} · {new Date(run.created_at).toLocaleString()}
          </div>
        </div>
        <div style={{display:"flex",gap:8}}>
          {isLive && (
            <button onClick={handleCancel} style={{
              padding:"8px 16px",background:"transparent",
              border:"1px solid #f8717140",borderRadius:10,
              color:"#f87171",fontSize:12,transition:".15s",
            }}>✕ Cancel</button>
          )}
        </div>
      </div>

      {/* Stage progress bar */}
      <div style={{
        background:"#1c1f2e",border:"1px solid #ffffff0f",
        borderRadius:16,padding:"20px 24px",marginBottom:20,
      }}>
        <div style={{display:"flex",gap:0}}>
          {stages.map((s,i) => (
            <div key={s.key} style={{display:"flex",alignItems:"center",flex:1,minWidth:0}}>
              <div style={{
                display:"flex",flexDirection:"column",alignItems:"flex-start",
                flex:1,minWidth:0,position:"relative",
              }}>
                <div style={{display:"flex",alignItems:"center",gap:10,marginBottom:8}}>
                  <div style={{
                    width:32,height:32,borderRadius:10,flexShrink:0,
                    display:"flex",alignItems:"center",justifyContent:"center",
                    background: s.done ? s.color+"30" : s.active ? s.color+"20" : "#ffffff0a",
                    border:`2px solid ${s.done||s.active ? s.color+"60" : "#ffffff10"}`,
                    fontSize:13,
                    boxShadow: s.active ? `0 0 16px ${s.color}40` : "none",
                    transition:".3s",
                  }}>
                    {s.done ? <span style={{color:s.color}}>✓</span>
                     : s.active ? <Spinner size={14} color={s.color}/>
                     : <span style={{color:"#5c5e78",fontSize:11,fontWeight:700}}>{i+1}</span>}
                  </div>
                  <div>
                    <div style={{
                      fontSize:13,fontWeight:600,fontFamily:"'Syne',sans-serif",
                      color: s.done||s.active ? "#f0f0f8" : "#5c5e78",
                    }}>{s.label}</div>
                    <div style={{fontSize:11,color:"#5c5e78"}}>{s.sub}</div>
                  </div>
                </div>
              </div>
              {i < stages.length-1 && (
                <div style={{
                  width:40,height:2,
                  background: s.done ? "linear-gradient(90deg,"+s.color+","+stages[i+1].color+")" : "#ffffff0f",
                  margin:"0 8px",flexShrink:0,borderRadius:1,transition:".5s",
                  marginBottom:8,
                }}/>
              )}
            </div>
          ))}
        </div>

        {/* Summary stats */}
        {(lookalikes.length>0 || contacts.length>0 || sendResults.length>0) && (
          <div style={{
            display:"flex",gap:20,paddingTop:16,
            borderTop:"1px solid #ffffff08",marginTop:8,
          }}>
            {[
              { label:"Lookalikes", value:lookalikes.length, color:"#60a5fa" },
              { label:"Contacts",   value:contacts.length,   color:"#a78bfa" },
              { label:"Sent",       value:sentCount+dryCount, color:"#34d399" },
              { label:"Failed",     value:failedCount,        color:"#f87171" },
            ].map(s => (
              <div key={s.label}>
                <div style={{fontSize:10,color:"#5c5e78",textTransform:"uppercase",letterSpacing:".5px"}}>{s.label}</div>
                <div style={{fontFamily:"'Syne',sans-serif",fontSize:20,fontWeight:700,color:s.color}}>{s.value}</div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Safety checkpoint banner */}
      {isCheckpoint && (
        <div style={{
          background:"#fbbf2412",border:"1px solid #fbbf2440",
          borderRadius:14,padding:"20px 24px",marginBottom:20,
          animation:"fadeUp .3s ease",
        }}>
          <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",gap:20}}>
            <div>
              <div style={{
                fontSize:14,fontWeight:600,color:"#fbbf24",
                fontFamily:"'Syne',sans-serif",marginBottom:4,
              }}>
                ⚠ Safety checkpoint
              </div>
              <div style={{fontSize:12,color:"#fbbf2490"}}>
                {contacts.length} recipients are queued. Review the list below before emails fire.
                This is irreversible.
              </div>
            </div>
            <div style={{display:"flex",gap:8,flexShrink:0}}>
              <button onClick={handleCancel} style={{
                padding:"9px 18px",background:"transparent",
                border:"1px solid #ffffff20",borderRadius:10,
                color:"#9b9cb8",fontSize:12,transition:".15s",
              }}>Cancel</button>
              <button onClick={handleConfirm} disabled={confirming} style={{
                padding:"9px 20px",
                background: confirming ? "#34d39960" : "#34d399",
                border:"none",borderRadius:10,
                color:"#000",fontFamily:"'Syne',sans-serif",
                fontSize:13,fontWeight:700,transition:".15s",
                display:"flex",alignItems:"center",gap:6,
              }}>
                {confirming ? <><Spinner size={13} color="#000"/>Confirming…</> : `✓ Send ${contacts.length} emails`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Error banner */}
      {isFailed && run.error && (
        <div style={{
          background:"#f8717112",border:"1px solid #f8717140",
          borderRadius:12,padding:"16px 20px",marginBottom:20,color:"#f87171",fontSize:13,
        }}>
          <strong>Pipeline failed:</strong> {run.error}
        </div>
      )}

      {/* Main grid */}
      <div style={{display:"grid",gridTemplateColumns:"1fr 1fr",gap:16}}>

        {/* Logs panel */}
        <div style={{
          background:"#1c1f2e",border:"1px solid #ffffff0f",
          borderRadius:14,overflow:"hidden",
        }}>
          <div style={{
            padding:"12px 16px",borderBottom:"1px solid #ffffff0f",
            display:"flex",alignItems:"center",justifyContent:"space-between",
          }}>
            <span style={{fontFamily:"'Syne',sans-serif",fontSize:13,fontWeight:600}}>
              Live logs
            </span>
            <div style={{display:"flex",alignItems:"center",gap:6}}>
              {isLive && <Spinner size={12} color="#6c63ff"/>}
              <span style={{fontSize:11,color:"#5c5e78",fontFamily:"'DM Mono',monospace"}}>
                {logs.length} entries
              </span>
            </div>
          </div>
          <div ref={logsRef} style={{
            height:320,overflowY:"auto",padding:"12px 16px",
            fontFamily:"'DM Mono',monospace",fontSize:11,lineHeight:1.7,
          }}>
            {logs.length === 0 ? (
              <div style={{color:"#5c5e78",textAlign:"center",paddingTop:40}}>
                {isLive ? "Waiting for logs…" : "No logs yet"}
              </div>
            ) : logs.map((l,i) => (
              <div key={i} style={{
                display:"flex",gap:8,marginBottom:2,
                animation:"slideIn .15s ease",
              }}>
                <span style={{color:"#5c5e78",flexShrink:0}}>
                  {new Date(l.ts).toTimeString().slice(0,8)}
                </span>
                <span style={{
                  color: LOG_COLORS[l.level] || LOG_COLORS.info,
                  wordBreak:"break-word",
                }}>{l.msg}</span>
              </div>
            ))}
          </div>
        </div>

        {/* Contacts panel */}
        <div style={{
          background:"#1c1f2e",border:"1px solid #ffffff0f",
          borderRadius:14,overflow:"hidden",
        }}>
          <div style={{
            padding:"12px 16px",borderBottom:"1px solid #ffffff0f",
            display:"flex",alignItems:"center",justifyContent:"space-between",
          }}>
            <span style={{fontFamily:"'Syne',sans-serif",fontSize:13,fontWeight:600}}>
              Contacts
            </span>
            <span style={{fontSize:11,color:"#5c5e78",fontFamily:"'DM Mono',monospace"}}>
              {contacts.length} found
            </span>
          </div>
          <div style={{height:320,overflowY:"auto"}}>
            {contacts.length === 0 ? (
              <div style={{
                color:"#5c5e78",textAlign:"center",paddingTop:40,fontSize:12,
              }}>
                {["stage1","pending"].includes(status) ? "Waiting for Stage 2…" : "No contacts found"}
              </div>
            ) : contacts.map((c,i) => {
              const result = sendResults.find(r=>r.email===c.email);
              return (
                <div key={i} style={{
                  display:"flex",alignItems:"center",gap:10,
                  padding:"10px 16px",borderBottom:"1px solid #ffffff06",
                  transition:".15s",
                }}
                onMouseEnter={e=>e.currentTarget.style.background="#ffffff04"}
                onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                  <Avatar name={c.name} color={AVATAR_COLORS[i%AVATAR_COLORS.length]}/>
                  <div style={{flex:1,minWidth:0}}>
                    <div style={{fontSize:12,fontWeight:500,truncate:"ellipsis",overflow:"hidden",whiteSpace:"nowrap"}}>
                      {c.name}
                    </div>
                    <div style={{fontSize:11,color:"#5c5e78",overflow:"hidden",whiteSpace:"nowrap",textOverflow:"ellipsis"}}>
                      {c.title} · {c.domain}
                    </div>
                    <div style={{
                      fontSize:10,color:"#6c63ff",
                      fontFamily:"'DM Mono',monospace",
                      overflow:"hidden",whiteSpace:"nowrap",textOverflow:"ellipsis",
                    }}>{c.email}</div>
                  </div>
                  <div style={{flexShrink:0}}>
                    {result ? (
                      <span style={{
                        fontSize:10,padding:"2px 7px",borderRadius:6,
                        background: result.status==="sent" ? "#34d39920"
                          : result.status==="dry_run" ? "#fbbf2420" : "#f8717120",
                        color: result.status==="sent" ? "#34d399"
                          : result.status==="dry_run" ? "#fbbf24" : "#f87171",
                        fontFamily:"'DM Mono',monospace",
                      }}>
                        {result.status==="sent" ? "✓ sent"
                          : result.status==="dry_run" ? "preview"
                          : "✗ failed"}
                      </span>
                    ) : (
                      <span style={{
                        fontSize:10,color:"#5c5e78",
                        fontFamily:"'DM Mono',monospace",
                      }}>{c.email_status||"—"}</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Lookalikes strip */}
      {lookalikes.length > 0 && (
        <div style={{
          marginTop:16,background:"#1c1f2e",border:"1px solid #ffffff0f",
          borderRadius:14,padding:"14px 20px",
        }}>
          <div style={{
            fontSize:11,color:"#5c5e78",textTransform:"uppercase",
            letterSpacing:".5px",marginBottom:10,fontWeight:600,
          }}>
            Lookalike domains ({lookalikes.length})
          </div>
          <div style={{display:"flex",flexWrap:"wrap",gap:8}}>
            {lookalikes.map(d => (
              <span key={d} style={{
                padding:"4px 12px",borderRadius:20,fontSize:12,
                background:"#60a5fa15",color:"#60a5fa",
                border:"1px solid #60a5fa30",
                fontFamily:"'DM Mono',monospace",
              }}>{d}</span>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ── History ───────────────────────────────────────────────────────────────────
function History({ runs, onRefresh, onView }) {
  return (
    <div style={{padding:"28px 40px",maxWidth:1100,margin:"0 auto",animation:"fadeUp .3s ease"}}>
      <div style={{display:"flex",alignItems:"center",justifyContent:"space-between",marginBottom:24}}>
        <div>
          <h1 style={{fontFamily:"'Syne',sans-serif",fontSize:22,fontWeight:700}}>Run history</h1>
          <p style={{color:"#9b9cb8",fontSize:13,marginTop:4}}>{runs.length} total runs</p>
        </div>
        <button onClick={onRefresh} style={{
          padding:"8px 16px",background:"#1c1f2e",
          border:"1px solid #ffffff15",borderRadius:10,
          color:"#9b9cb8",fontSize:12,transition:".15s",
        }}>↺ Refresh</button>
      </div>

      {runs.length === 0 ? (
        <div style={{
          background:"#1c1f2e",border:"1px solid #ffffff0f",borderRadius:16,
          padding:48,textAlign:"center",color:"#5c5e78",
        }}>
          <div style={{fontSize:32,marginBottom:12}}>📭</div>
          No runs yet. Start one from the dashboard.
        </div>
      ) : (
        <div style={{background:"#1c1f2e",border:"1px solid #ffffff0f",borderRadius:16,overflow:"hidden"}}>
          <table style={{width:"100%",borderCollapse:"collapse"}}>
            <thead>
              <tr style={{background:"#0f1117"}}>
                {["Run ID","Domain","Lookalikes","Contacts","Sent","Status","Started"].map(h=>(
                  <th key={h} style={{
                    padding:"10px 16px",textAlign:"left",
                    fontSize:10,color:"#5c5e78",fontWeight:600,
                    textTransform:"uppercase",letterSpacing:".5px",
                    borderBottom:"1px solid #ffffff0f",
                  }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {runs.map(r => (
                <tr key={r.run_id}
                  onClick={() => onView(r)}
                  style={{cursor:"pointer",transition:".15s"}}
                  onMouseEnter={e=>e.currentTarget.style.background="#ffffff04"}
                  onMouseLeave={e=>e.currentTarget.style.background="transparent"}>
                  <td style={{padding:"12px 16px",fontFamily:"'DM Mono',monospace",fontSize:12,color:"#6c63ff",borderBottom:"1px solid #ffffff06"}}>
                    #{r.run_id}
                  </td>
                  <td style={{padding:"12px 16px",fontWeight:500,borderBottom:"1px solid #ffffff06"}}>{r.domain}</td>
                  <td style={{padding:"12px 16px",color:"#60a5fa",fontFamily:"'DM Mono',monospace",fontSize:12,borderBottom:"1px solid #ffffff06"}}>{r.lookalikes}</td>
                  <td style={{padding:"12px 16px",color:"#a78bfa",fontFamily:"'DM Mono',monospace",fontSize:12,borderBottom:"1px solid #ffffff06"}}>{r.contacts}</td>
                  <td style={{padding:"12px 16px",color:"#34d399",fontFamily:"'DM Mono',monospace",fontSize:12,borderBottom:"1px solid #ffffff06"}}>{r.sent}</td>
                  <td style={{padding:"12px 16px",borderBottom:"1px solid #ffffff06"}}><Badge status={r.status}/></td>
                  <td style={{padding:"12px 16px",color:"#5c5e78",fontSize:11,fontFamily:"'DM Mono',monospace",borderBottom:"1px solid #ffffff06"}}>
                    {new Date(r.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}